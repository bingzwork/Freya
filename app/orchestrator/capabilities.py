"""Executable Capability Implementations for Central Orchestrator.

This module provides concrete implementations of the 14 built-in capabilities
that integrate with FreyaAgent's subsystems.
"""

import logging
import mimetypes
import os
import shutil
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
        self._agent_memory = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_agent_memory(self, memory):
        """Set the agent's memory systems."""
        self._agent_memory = memory

    def action_store(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Store information in memory."""
        if not self._agent_memory:
            return {"success": False, "error": "Memory not initialized"}

        content = inputs.get("content", "")
        memory_type = inputs.get("type", "experience")
        metadata = inputs.get("metadata", {})

        try:
            if memory_type == "experience" and hasattr(self._agent_memory, 'experience_memory'):
                result = self._agent_memory.experience_memory.store(content, metadata)
            elif memory_type == "project" and hasattr(self._agent_memory, 'memory'):
                result = self._agent_memory.memory.record(content, metadata)
            elif memory_type == "task" and hasattr(self._agent_memory, 'task_memory'):
                result = self._agent_memory.task_memory.store(inputs.get("task_id", ""), content)
            else:
                return {"success": False, "error": f"Unknown memory type: {memory_type}"}

            self._publish_event("memory.stored", {"type": memory_type, "content": content[:100]})
            return {"success": True, "stored": True, "id": str(result) if result else None}
        except Exception as e:
            logger.error(f"Memory store failed: {e}")
            return {"success": False, "error": str(e)}

    def action_retrieve(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve information from memory."""
        if not self._agent_memory:
            return {"success": False, "error": "Memory not initialized"}

        query = inputs.get("query", "")
        memory_type = inputs.get("type", "unified")
        limit = inputs.get("limit", 10)

        try:
            if memory_type == "unified" and hasattr(self._agent_memory, 'unified_retrieval'):
                results = self._agent_memory.unified_retrieval.retrieve(query, limit=limit)
            elif memory_type == "experience" and hasattr(self._agent_memory, 'experience_memory'):
                results = self._agent_memory.experience_memory.search(query, limit=limit)
            elif memory_type == "project" and hasattr(self._agent_memory, 'memory'):
                results = self._agent_memory.memory.search(query, limit=limit)
            elif memory_type == "semantic" and hasattr(self._agent_memory, 'semantic_memory'):
                results = self._agent_memory.semantic_memory.search(query, limit=limit)
            else:
                return {"success": False, "error": f"Unknown memory type: {memory_type}"}

            return {"success": True, "results": results}
        except Exception as e:
            logger.error(f"Memory retrieve failed: {e}")
            return {"success": False, "error": str(e)}

    def action_consolidate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger memory consolidation."""
        if not self._agent_memory or not hasattr(self._agent_memory, 'consolidation_engine'):
            return {"success": False, "error": "Consolidation engine not available"}

        try:
            self._agent_memory.consolidation_engine.run_consolidation()
            self._publish_event("memory.consolidated", {})
            return {"success": True, "consolidated": True}
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
        """Create a new plan."""
        if not self._planner:
            return {"success": False, "error": "Planner not initialized"}

        task = inputs.get("task", "")
        goal_id = inputs.get("goal_id")
        context = inputs.get("context", {})

        try:
            plan = self._planner.create_plan(task, goal_id=goal_id, context=context)
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
        """Adaptively replan after failure."""
        if not self._decision_manager:
            return {"success": False, "error": "Decision manager not initialized"}

        # This is handled by the agent's _replan_after_failure method
        self._publish_event("plan.replanned", {"task": inputs.get("task", "")})
        return {"success": True, "replanned": True}

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
    """Continuous learning capability."""

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
        self._agent = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_agent(self, agent):
        self._agent = agent

    def action_reflect(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Generate reflection on completed work."""
        if not self._agent or not hasattr(self._agent, 'reflection_engine'):
            return {"success": False, "error": "Reflection engine not available"}

        task_description = inputs.get("task", "")
        outcome = inputs.get("outcome", "success")
        eval_result = inputs.get("eval_result")

        try:
            from app.software_engineering_knowledge.reflection import ReflectionContext
            context = ReflectionContext(
                task_description=task_description,
                original_request=task_description,
                outcome=outcome,
                eval_result=eval_result,
            )
            reflection = self._agent.reflection_engine.create_reflection(context)
            self._agent.reflection_engine.store_reflection(reflection)
            self._publish_event("learning.reflected", {"task": task_description[:100], "reflection_id": reflection.id})
            return {"success": True, "reflection_id": reflection.id}
        except Exception as e:
            logger.error(f"Reflection failed: {e}")
            return {"success": False, "error": str(e)}

    def action_consolidate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run memory consolidation."""
        if not self._agent or not hasattr(self._agent, 'consolidation_engine'):
            return {"success": False, "error": "Consolidation engine not available"}

        try:
            self._agent.consolidation_engine.run_consolidation()
            self._publish_event("learning.consolidated", {})
            return {"success": True, "consolidated": True}
        except Exception as e:
            logger.error(f"Consolidation failed: {e}")
            return {"success": False, "error": str(e)}

    def action_store_lesson(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Store an engineering lesson."""
        if not self._agent or not hasattr(self._agent, 'engineering_lessons'):
            return {"success": False, "error": "Engineering lessons not available"}

        title = inputs.get("title", "")
        description = inputs.get("description", "")
        lesson_type = inputs.get("lesson_type", "pattern")
        category = inputs.get("category", "task")
        severity = inputs.get("severity", "recommended")
        tags = inputs.get("tags", [])
        rationale = inputs.get("rationale", "")

        try:
            from app.memory.engineering_lessons import LessonType, LessonSeverity
            self._agent.engineering_lessons.store(
                title=title,
                description=description,
                lesson_type=LessonType(lesson_type),
                category=category,
                severity=LessonSeverity(severity),
                tags=tags,
                rationale=rationale,
            )
            self._publish_event("learning.lesson_stored", {"title": title})
            return {"success": True, "stored": True}
        except Exception as e:
            logger.error(f"Lesson storage failed: {e}")
            return {"success": False, "error": str(e)}


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
        """Publish an event."""
        if not self._event_bus:
            return {"success": False, "error": "Event bus not initialized"}

        event_type = inputs.get("event_type", "")
        data = inputs.get("data", {})
        priority = inputs.get("priority", "normal")

        try:
            from app.core.events import EventPriority
            self._event_bus.publish(event_type, data, priority=EventPriority[priority.upper()])
            return {"success": True, "published": True, "event_type": event_type}
        except Exception as e:
            logger.error(f"Event publish failed: {e}")
            return {"success": False, "error": str(e)}

    def action_subscribe(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Subscribe to events."""
        if not self._event_bus:
            return {"success": False, "error": "Event bus not initialized"}

        # Note: Actual subscription requires a callback function
        # This is a placeholder for the capability
        return {"success": True, "message": "Subscriptions require callback registration in code"}

    def action_get_history(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Get event history."""
        if not self._event_bus:
            return {"success": False, "error": "Event bus not initialized"}

        try:
            limit = inputs.get("limit", 100)
            history = self._event_bus.get_history(limit=limit)
            return {"success": True, "events": history}
        except Exception as e:
            logger.error(f"Event history failed: {e}")
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
    """Knowledge storage and retrieval capability."""

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
        self._agent = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_agent(self, agent):
        self._agent = agent

    def action_search(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Search knowledge base."""
        if not self._agent:
            return {"success": False, "error": "Agent not initialized"}

        query = inputs.get("query", "")
        memory_type = inputs.get("memory_type", "unified")
        limit = inputs.get("limit", 10)

        try:
            if memory_type == "unified" and hasattr(self._agent, 'unified_retrieval'):
                results = self._agent.unified_retrieval.retrieve(query, limit=limit)
            elif memory_type == "semantic" and hasattr(self._agent, 'semantic_memory'):
                results = self._agent.semantic_memory.search(query, limit=limit)
            elif memory_type == "episodic" and hasattr(self._agent, 'episodic_memory'):
                results = self._agent.episodic_memory.search(query, limit=limit)
            else:
                return {"success": False, "error": f"Unknown memory type: {memory_type}"}

            return {"success": True, "results": results}
        except Exception as e:
            logger.error(f"Knowledge search failed: {e}")
            return {"success": False, "error": str(e)}

    def action_store_knowledge(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Store knowledge."""
        if not self._agent or not hasattr(self._agent, 'semantic_memory'):
            return {"success": False, "error": "Semantic memory not available"}

        content = inputs.get("content", "")
        metadata = inputs.get("metadata", {})

        try:
            result = self._agent.semantic_memory.store(content, metadata)
            self._publish_event("knowledge.stored", {"content": content[:100]})
            return {"success": True, "stored": True, "id": str(result) if result else None}
        except Exception as e:
            logger.error(f"Knowledge storage failed: {e}")
            return {"success": False, "error": str(e)}


# =============================================================================
# Reasoning Engine Capability
# =============================================================================

class ReasoningEngineCapability(BaseCapability):
    """Logical reasoning capability."""

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
        self._agent = None

    def _initialize(self) -> bool:
        return True

    def _activate(self) -> bool:
        return True

    def _deactivate(self) -> bool:
        return True

    def set_agent(self, agent):
        self._agent = agent

    def action_analyze(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze a problem using reasoning."""
        if not self._agent or not self._agent.llm:
            return {"success": False, "error": "LLM not available"}

        problem = inputs.get("problem", "")
        context = inputs.get("context", "")

        try:
            prompt = f"""Analyze this problem step by step:

Problem: {problem}

Context: {context}

Provide a structured analysis with:
1. Problem decomposition
2. Key factors
3. Potential approaches
4. Recommended solution path"""

            answer = self._agent.llm.ask(prompt)
            self._publish_event("reasoning.analyzed", {"problem": problem[:100]})
            return {"success": True, "analysis": answer}
        except Exception as e:
            logger.error(f"Reasoning analysis failed: {e}")
            return {"success": False, "error": str(e)}

    def action_synthesize(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize information from multiple sources."""
        if not self._agent or not self._agent.llm:
            return {"success": False, "error": "LLM not available"}

        sources = inputs.get("sources", [])
        task = inputs.get("task", "")

        try:
            source_text = "\n\n".join([f"Source {i+1}: {s}" for i, s in enumerate(sources)])
            prompt = f"""Synthesize the following information for this task:

Task: {task}

Sources:
{source_text}

Provide a coherent synthesis that addresses the task."""

            answer = self._agent.llm.ask(prompt)
            self._publish_event("reasoning.synthesized", {"task": task[:100]})
            return {"success": True, "synthesis": answer}
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
                return unquote(parsed.path)
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

    capabilities = [
        MemoryManagementCapability(),
        PlanningEngineCapability(),
        CodeExecutionCapability(),
        DecisionEngineCapability(),
        LearningPipelineCapability(),
        SystemMonitoringCapability(),
        CommunicationHubCapability(),
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
    ]

    if agent:
        # Wire capabilities to agent
        for cap in capabilities:
            if isinstance(cap, MemoryManagementCapability):
                cap.set_agent_memory(agent)
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
                cap.set_agent(agent)
            elif isinstance(cap, SystemMonitoringCapability) and hasattr(agent, 'observability'):
                cap.set_observability(agent.observability)
            elif isinstance(cap, CommunicationHubCapability) and hasattr(agent, 'event_bus'):
                cap.set_event_bus(agent.event_bus)
            elif isinstance(cap, ToolRegistryCapability):
                cap.set_tools(agent.tools)
            elif isinstance(cap, SafetyGuardCapability) and hasattr(agent, 'safety_gate'):
                cap.set_safety_gate(agent.safety_gate)
            elif isinstance(cap, KnowledgeBaseCapability):
                cap.set_agent(agent)
            elif isinstance(cap, ReasoningEngineCapability):
                cap.set_agent(agent)
            elif isinstance(cap, OrchestrationCoreCapability) and hasattr(agent, 'orchestrator'):
                cap.set_orchestrator(agent.orchestrator)
            elif isinstance(cap, FailureRecoveryCapability):
                cap.set_agent(agent)

    return capabilities