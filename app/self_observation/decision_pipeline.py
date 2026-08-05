"""Unified Runtime Decision Pipeline for Self Observation.

Consolidates runtime information from all subsystems before major autonomous decisions.
Integrates with existing: Orchestrator, Decision Manager, World Model, Memory, Monitoring, etc.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from app.core.events import get_event_bus, Event
from app.core.observability import get_observability_hub
# Lazy imports to avoid circular dependency
# from app.orchestrator.orchestrator import get_orchestrator, CentralOrchestrator
from app.decision.manager import DecisionManager, get_default_manager
from app.world_model.model import WorldModel, create_world_model
from app.memory.unified_retrieval import UnifiedRetrieval
from app.failure_recovery.orchestrator import RecoveryOrchestrator
from app.long_term_autonomy.manager import AutonomyManager

from .models import (
    DecisionPipelineContext,
    DecisionPipelineStage,
    DecisionPipelineResult,
)

# Type checking imports to avoid circular dependency
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.orchestrator.orchestrator import CentralOrchestrator

logger = logging.getLogger(__name__)


@dataclass
class PipelineStageResult:
    """Result of a single pipeline stage."""
    stage: DecisionPipelineStage
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: Optional[str] = None


class UnifiedRuntimeDecisionPipeline:
    """
    Unified Runtime Decision Pipeline.

    Consolidates runtime information from all subsystems before major autonomous decisions.
    Gathers and evaluates:
    - Current goals
    - Active plans
    - Runtime health
    - Resource availability
    - Monitoring state
    - World Model
    - Memory
    - Knowledge Retrieval
    - Current task execution
    - Failure Recovery state
    - Safety state

    Provides a unified decision context for downstream planning and execution.
    """

    def __init__(
        self,
        orchestrator: "Optional[CentralOrchestrator]" = None,
        decision_manager: Optional[DecisionManager] = None,
        world_model: Optional[WorldModel] = None,
        memory_retrieval: Optional[UnifiedRetrieval] = None,
        failure_recovery: Optional[RecoveryOrchestrator] = None,
        autonomy_manager: Optional[AutonomyManager] = None,
    ):
        """
        Initialize the pipeline with subsystem integrations.

        Args:
            orchestrator: Central orchestrator instance
            decision_manager: Decision manager instance
            world_model: World model instance
            memory_retrieval: Unified memory retrieval instance
            failure_recovery: Failure recovery orchestrator
            autonomy_manager: Long-term autonomy manager
        """
        self._orchestrator = orchestrator
        self._decision_manager = decision_manager
        self._world_model = world_model
        self._memory_retrieval = memory_retrieval
        self._failure_recovery = failure_recovery
        self._autonomy_manager = autonomy_manager

        self._event_bus = get_event_bus()
        self._observability = get_observability_hub()

        self._lock = threading.RLock()
        self._running = False
        self._pipeline_thread: Optional[threading.Thread] = None
        self._pipeline_interval = 30.0  # seconds

        # Pipeline history
        self._pipeline_history: List[DecisionPipelineResult] = []
        self._max_history = 100

        # Stage implementations
        self._stage_handlers: Dict[DecisionPipelineStage, Callable] = {
            DecisionPipelineStage.OBSERVE: self._stage_observe,
            DecisionPipelineStage.GATHER_CONTEXT: self._stage_gather_context,
            DecisionPipelineStage.IDENTIFY_ACTIONS: self._stage_identify_actions,
            DecisionPipelineStage.EVALUATE_OPTIONS: self._stage_evaluate_options,
            DecisionPipelineStage.ESTIMATE_RISK_BENEFIT: self._stage_estimate_risk_benefit,
            DecisionPipelineStage.CHOOSE_BEST: self._stage_choose_best,
            DecisionPipelineStage.EXECUTE: self._stage_execute,
            DecisionPipelineStage.OBSERVE_OUTCOME: self._stage_observe_outcome,
            DecisionPipelineStage.LEARN: self._stage_learn,
        }

        # Import ComponentInfo and ComponentType
        from app.core.observability import ComponentInfo, ComponentType

        # Register with observability
        self._observability.register_component(
            ComponentInfo(
                name="UnifiedRuntimeDecisionPipeline",
                component_type=ComponentType.PIPELINE,
                description="Unified runtime decision pipeline for self-observation",
                version="1.0.0"
            )
        )

        # Subscribe to relevant events
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        """Subscribe to events from integrated subsystems."""
        self._event_bus.subscribe("orchestrator.intent_executed", self._on_intent_executed)
        self._event_bus.subscribe("workflow.completed", self._on_workflow_completed)
        self._event_bus.subscribe("workflow.failed", self._on_workflow_failed)
        self._event_bus.subscribe("decision.made", self._on_decision_made)
        self._event_bus.subscribe("failure_recovery.started", self._on_recovery_started)
        self._event_bus.subscribe("failure_recovery.completed", self._on_recovery_completed)
        self._event_bus.subscribe("autonomy.cycle_completed", self._on_autonomy_cycle)

    def start(self) -> None:
        """Start the pipeline background collection."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._pipeline_thread = threading.Thread(
            target=self._pipeline_loop,
            daemon=True,
            name="UnifiedDecisionPipeline"
        )
        self._pipeline_thread.start()
        logger.info("UnifiedRuntimeDecisionPipeline started")

    def stop(self) -> None:
        """Stop the pipeline."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._pipeline_thread and self._pipeline_thread.is_alive():
            self._pipeline_thread.join(timeout=5.0)

        logger.info("UnifiedRuntimeDecisionPipeline stopped")

    def _pipeline_loop(self) -> None:
        """Background pipeline maintenance loop."""
        while self._running:
            try:
                # Periodic context refresh
                self._refresh_context_cache()
            except Exception as e:
                logger.error(f"Error in pipeline loop: {e}")

            time.sleep(self._pipeline_interval)

    def _refresh_context_cache(self) -> None:
        """Refresh cached context from subsystems."""
        # This runs periodically to keep context fresh
        # The full pipeline runs on-demand for decisions
        pass

    def run_pipeline(
        self,
        trigger_context: Optional[Dict[str, Any]] = None,
        stop_at_stage: Optional[DecisionPipelineStage] = None,
    ) -> DecisionPipelineResult:
        """
        Run the complete decision pipeline.

        Args:
            trigger_context: Optional context that triggered the pipeline
            stop_at_stage: Optional stage to stop at (for partial evaluation)

        Returns:
            DecisionPipelineResult with unified decision context
        """
        pipeline_id = f"pipeline_{uuid4().hex[:8]}"
        start_time = time.perf_counter()

        logger.info(f"[{pipeline_id}] Starting unified runtime decision pipeline")

        # Initialize context
        context = DecisionPipelineContext(pipeline_id=pipeline_id)
        if trigger_context:
            context.metadata.update(trigger_context)

        stage_times = {}
        stage_results = {}

        # Execute stages in order
        stages = list(DecisionPipelineStage)
        for stage in stages:
            if stop_at_stage and stage == stop_at_stage:
                break

            stage_start = time.perf_counter()
            logger.debug(f"[{pipeline_id}] Executing stage: {stage.value}")

            try:
                handler = self._stage_handlers.get(stage)
                if handler:
                    result = handler(context)
                    stage_result = PipelineStageResult(
                        stage=stage,
                        success=True,
                        data=result,
                        duration_ms=(time.perf_counter() - stage_start) * 1000
                    )
                    stage_results[stage.value] = result
                else:
                    stage_result = PipelineStageResult(
                        stage=stage,
                        success=False,
                        error=f"No handler for stage {stage.value}",
                        duration_ms=(time.perf_counter() - stage_start) * 1000
                    )
            except Exception as e:
                logger.error(f"[{pipeline_id}] Stage {stage.value} failed: {e}")
                stage_result = PipelineStageResult(
                    stage=stage,
                    success=False,
                    error=str(e),
                    duration_ms=(time.perf_counter() - stage_start) * 1000
                )

            stage_times[stage.value] = stage_result.duration_ms
            context.stage_results[stage.value] = {
                "success": stage_result.success,
                "data": stage_result.data,
                "error": stage_result.error
            }

            if not stage_result.success:
                logger.warning(f"[{pipeline_id}] Stage {stage.value} failed, continuing pipeline")

            context.stage = stage

        # Finalize
        context.collection_time_ms = (time.perf_counter() - start_time) * 1000

        # Build result
        result = DecisionPipelineResult(
            pipeline_id=pipeline_id,
            context=context,
            stage_times=stage_times,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        # Store in history
        with self._lock:
            self._pipeline_history.append(result)
            if len(self._pipeline_history) > self._max_history:
                self._pipeline_history.pop(0)

        # Emit event
        self._event_bus.emit(
            "unified_decision_pipeline.completed",
            data={
                "pipeline_id": pipeline_id,
                "stages_completed": len(stage_results),
                "collection_time_ms": context.collection_time_ms,
                "has_chosen_action": result.chosen_action is not None,
            },
            source="UnifiedRuntimeDecisionPipeline"
        )

        logger.info(
            f"[{pipeline_id}] Pipeline completed in {context.collection_time_ms:.1f}ms, "
            f"stages: {len(stage_results)}"
        )

        return result

    # ============================================================
    # Pipeline Stage Implementations
    # ============================================================

    def _stage_observe(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 1: Observe - Capture current system state."""
        result = {}

        # Get orchestrator state
        if self._orchestrator:
            orch_status = self._orchestrator.get_system_status()
            result["orchestrator"] = orch_status
            result["orchestrator_state"] = self._orchestrator.state.value

        # Get observability health
        health = self._observability.get_health()
        result["system_health"] = health.get("status", "unknown")
        result["health_score"] = health.get("healthy", 0) / max(health.get("components", 1), 1) if health.get("components") else 0
        result["health_issues"] = []
        if health.get("unhealthy", 0) > 0:
            result["health_issues"].append(f"{health['unhealthy']} unhealthy components")
        if health.get("degraded", 0) > 0:
            result["health_issues"].append(f"{health['degraded']} degraded components")

        # Get active alerts
        alerts = self._observability.get_active_alerts()
        result["active_alerts"] = [
            {"id": a.get("id"), "rule": a.get("rule"), "severity": a.get("severity"), "message": a.get("message")}
            for a in alerts
        ]

        # Update context
        context.system_health = result["system_health"]
        context.health_score = result.get("health_score", 0.0)
        context.health_issues = result["health_issues"]
        context.active_alerts = result["active_alerts"]

        return result

    def _stage_gather_context(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 2: Gather Context - Collect from all subsystems."""
        result = {}

        # Current goals from orchestrator/memory
        if self._orchestrator and self._orchestrator._memory_retrieval:
            # Goals would come from goal management system
            # For now, use what's in orchestrator config or context
            context.active_goals = context.metadata.get("active_goals", [])
            result["active_goals"] = context.active_goals

        # Active plans from workflow composer
        if self._orchestrator and self._orchestrator._workflow_composer:
            wf_stats = self._orchestrator._workflow_composer.get_stats()
            context.current_plans = []  # Would need plan details
            context.plan_status = wf_stats.get("by_status", {})
            result["workflow_stats"] = wf_stats

        # Resource availability from world model
        if self._world_model:
            snapshot = self._world_model.get_snapshot()
            context.cpu_percent = snapshot.resources.cpu_percent
            context.memory_percent = snapshot.resources.memory_percent
            context.disk_percent = snapshot.resources.disk_percent
            context.project_context = snapshot.project.to_dict()
            result["resources"] = {
                "cpu_percent": snapshot.resources.cpu_percent,
                "memory_percent": snapshot.resources.memory_percent,
                "disk_percent": snapshot.resources.disk_percent,
            }
            result["project_context"] = snapshot.project.to_dict()
            context.world_snapshot = snapshot.to_dict()

        # Monitoring metrics
        system_metrics = self._observability.get_system_metrics()
        context.recent_metrics = system_metrics
        result["system_metrics"] = system_metrics

        # Available tools
        if self._orchestrator and self._orchestrator._capability_registry:
            caps = self._orchestrator._capability_registry.list_capabilities(active_only=True)
            context.available_tools = [c.name for c in caps]
            result["available_capabilities"] = [c.name for c in caps]

        return result

    def _stage_identify_actions(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 3: Identify Actions - Determine available actions based on context."""
        result = {}
        actions = []

        # From active goals: what actions advance goals?
        for goal in context.active_goals:
            actions.append({
                "type": "goal_action",
                "source": goal.get("id", "unknown"),
                "description": f"Advance goal: {goal.get('name', 'unknown')}",
                "priority": goal.get("priority", "medium"),
            })

        # From active workflows: what next steps?
        if self._orchestrator and self._orchestrator._task_executor:
            active_wfs = self._orchestrator._task_executor.list_active_workflows()
            for wf_id in active_wfs:
                actions.append({
                    "type": "workflow_continuation",
                    "source": wf_id,
                    "description": f"Continue workflow {wf_id}",
                    "priority": "high",
                })

        # From failure recovery: what recovery actions needed?
        if self._failure_recovery:
            # Check for failures needing action
            failures = self._failure_recovery.get_failure_history(limit=10)
            for f in failures:
                if f.get("status") == "pending":
                    actions.append({
                        "type": "recovery_action",
                        "source": f.get("workflow_id"),
                        "description": f"Recover from {f.get('error_type')}: {f.get('error')}",
                        "priority": "critical",
                    })

        # From autonomy: self-initiated actions
        if self._autonomy_manager:
            # Would check for pending autonomous actions
            pass

        # Safety actions
        if context.pending_approvals:
            for approval in context.pending_approvals:
                actions.append({
                    "type": "safety_approval",
                    "source": approval.get("id"),
                    "description": f"Approval needed: {approval.get('title')}",
                    "priority": "high",
                })

        context.metadata["identified_actions"] = actions
        result["actions"] = actions
        result["action_count"] = len(actions)

        return result

    def _stage_evaluate_options(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 4: Evaluate Options - Use DecisionManager to evaluate."""
        result = {}

        actions = context.metadata.get("identified_actions", [])
        if not actions:
            result["evaluated_options"] = []
            return result

        if not self._decision_manager:
            result["evaluated_options"] = actions
            return result

        # Group actions by type and evaluate
        evaluated = []
        for action in actions[:10]:  # Limit to top 10
            # Use decision manager's simplified interface
            try:
                from app.decision.models import DecisionOption, DecisionType, DecisionCategory
                options = [
                    DecisionOption(
                        name=action.get("description", "Action"),
                        action=action.get("type", "execute"),
                        description=action.get("description", ""),
                        decision_type=DecisionType.TASK_DECOMPOSITION,
                        category=DecisionCategory.EXECUTION,
                        estimated_success=0.7,
                        estimated_effort=0.5,
                        estimated_impact=0.6,
                        metadata=action,
                    )
                ]

                decision_context = self._build_decision_context(context, action)
                decision_result = self._decision_manager.decide(decision_context, options)

                evaluated.append({
                    "action": action,
                    "decision_result": {
                        "chosen": decision_result.chosen_option.name if decision_result.chosen_option else None,
                        "confidence": decision_result.confidence,
                        "risk_level": decision_result.risk_level,
                        "should_execute": decision_result.should_execute,
                        "requires_approval": decision_result.requires_approval,
                        "rationale": decision_result.rationale,
                    },
                    "priority": action.get("priority", "medium"),
                })

            except Exception as e:
                logger.warning(f"Failed to evaluate action {action}: {e}")
                evaluated.append({
                    "action": action,
                    "decision_result": None,
                    "error": str(e),
                    "priority": action.get("priority", "medium"),
                })

        result["evaluated_options"] = evaluated

        # Sort by priority and confidence
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        evaluated.sort(key=lambda x: (
            priority_order.get(x["priority"], 4),
            -(x["decision_result"]["confidence"] if x["decision_result"] else 0)
        ))

        return result

    def _stage_estimate_risk_benefit(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 5: Estimate Risk/Benefit - Aggregate risk and benefit analysis."""
        result = {}

        evaluated = context.stage_results.get("evaluate_options", {}).get("data", {}).get("evaluated_options", [])

        total_risk = 0.0
        total_benefit = 0.0
        risk_factors = []
        benefit_factors = []

        for opt in evaluated:
            dr = opt.get("decision_result")
            if dr:
                risk_map = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}
                risk = risk_map.get(dr.get("risk_level", "low"), 0.1)
                benefit = dr.get("confidence", 0.5) * dr.get("estimated_impact", 0.5)

                total_risk += risk * (1.0 - dr.get("confidence", 0.5))
                total_benefit += benefit * dr.get("confidence", 0.5)

                if risk > 0.5:
                    risk_factors.append(f"{opt['action']['description']}: {dr['risk_level']} risk")
                if benefit > 0.5:
                    benefit_factors.append(f"{opt['action']['description']}: high benefit")

        # Add system-level risk factors
        if context.health_score < 0.5:
            total_risk += 0.3
            risk_factors.append("System health degraded")

        if context.memory_percent > 90:
            total_risk += 0.2
            risk_factors.append("High memory usage")

        if len(context.active_alerts) > 5:
            total_risk += 0.2
            risk_factors.append(f"Many active alerts ({len(context.active_alerts)})")

        # Add recovery state risk
        if context.recovery_success_rate < 0.5:
            total_risk += 0.2
            risk_factors.append("Low recovery success rate")

        result["total_risk_score"] = min(1.0, total_risk)
        result["total_benefit_score"] = min(1.0, total_benefit)
        result["risk_factors"] = risk_factors
        result["benefit_factors"] = benefit_factors
        result["net_score"] = result["total_benefit_score"] - result["total_risk_score"]

        return result

    def _stage_choose_best(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 6: Choose Best - Select the optimal action."""
        result = {}

        evaluated = context.stage_results.get("evaluate_options", {}).get("data", {}).get("evaluated_options", [])
        risk_benefit = context.stage_results.get("estimate_risk_benefit", {}).get("data", {})

        if not evaluated:
            result["chosen_action"] = None
            result["reason"] = "No actions available"
            return result

        # Select highest priority with acceptable risk/confidence
        chosen = evaluated[0]
        dr = chosen.get("decision_result")

        if dr and dr.get("should_execute") and dr.get("confidence", 0) >= 0.5:
            result["chosen_action"] = chosen["action"]
            result["decision_result"] = dr
            result["confidence"] = dr.get("confidence", 0)
            result["risk_level"] = dr.get("risk_level", "low")
            result["rationale"] = dr.get("rationale", "")
            result["should_execute"] = dr.get("should_execute", True)
            result["requires_approval"] = dr.get("requires_approval", False)
        else:
            # No good option found
            result["chosen_action"] = None
            result["reason"] = "No action meets confidence/risk thresholds"
            if dr:
                result["best_available"] = chosen["action"]
                result["best_confidence"] = dr.get("confidence", 0)
                result["best_risk"] = dr.get("risk_level", "unknown")

        # Alternatives
        result["alternatives"] = [
            {
                "action": e["action"],
                "confidence": e.get("decision_result", {}).get("confidence", 0),
                "risk": e.get("decision_result", {}).get("risk_level", "unknown"),
            }
            for e in evaluated[1:4]
        ]

        return result

    def _stage_execute(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 7: Execute - Execute the chosen action (if auto-execute)."""
        result = {}

        chosen = context.stage_results.get("choose_best", {}).get("data", {}).get("chosen_action")
        should_execute = context.stage_results.get("choose_best", {}).get("data", {}).get("should_execute", False)
        requires_approval = context.stage_results.get("choose_best", {}).get("data", {}).get("requires_approval", False)

        if not chosen:
            result["executed"] = False
            result["reason"] = "No action chosen"
            return result

        if requires_approval:
            result["executed"] = False
            result["reason"] = "Requires human approval"
            result["awaiting_approval"] = True
            return result

        if not should_execute:
            result["executed"] = False
            result["reason"] = "Auto-execution not recommended"
            return result

        # Execute via orchestrator or appropriate subsystem
        try:
            action_type = chosen.get("type")
            if action_type == "goal_action":
                # Would trigger goal advancement
                result["executed"] = True
                result["method"] = "goal_advancement"
            elif action_type == "workflow_continuation":
                # Workflow continues automatically
                result["executed"] = True
                result["method"] = "workflow_auto_continue"
            elif action_type == "recovery_action":
                if self._failure_recovery:
                    # Trigger recovery
                    result["executed"] = True
                    result["method"] = "failure_recovery"
            else:
                result["executed"] = False
                result["reason"] = f"Unknown action type: {action_type}"

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            result["executed"] = False
            result["error"] = str(e)

        return result

    def _stage_observe_outcome(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 8: Observe Outcome - Monitor execution results."""
        result = {}

        execution = context.stage_results.get("execute", {}).get("data", {})

        if not execution.get("executed"):
            result["outcome"] = "not_executed"
            result["reason"] = execution.get("reason", "Unknown")
            return result

        # In a real implementation, this would wait for and observe the outcome
        # For now, we record that execution was initiated
        result["outcome"] = "initiated"
        result["action"] = execution.get("method", "unknown")
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        return result

    def _stage_learn(self, context: DecisionPipelineContext) -> Dict[str, Any]:
        """Stage 9: Learn - Record outcome for future decisions."""
        result = {}

        # Record decision in history for learning
        chosen = context.stage_results.get("choose_best", {}).get("data", {}).get("chosen_action")
        dr = context.stage_results.get("choose_best", {}).get("data", {}).get("decision_result")

        if chosen and dr and self._decision_manager:
            try:
                decision_id = context.pipeline_id
                # Would record outcome when actually observed
                # For now, just record the decision context
                from app.decision.history import DecisionRecord
                record = DecisionRecord(
                    decision_id=decision_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    component="unified_pipeline",
                    chosen_option=dr.get("chosen", ""),
                    confidence=dr.get("confidence", 0),
                    risk_level=dr.get("risk_level", "low"),
                    should_execute=dr.get("should_execute", False),
                    requires_approval=dr.get("requires_approval", False),
                    metadata={
                        "pipeline_context": {
                            "health_score": context.health_score,
                            "active_goals": len(context.active_goals),
                            "available_actions": len(context.metadata.get("identified_actions", [])),
                        }
                    }
                )
                self._decision_manager.history.add_record(record)
                result["recorded"] = True
            except Exception as e:
                logger.warning(f"Failed to record decision for learning: {e}")
                result["recorded"] = False
                result["error"] = str(e)

        # Also feed into autonomous learning if available
        if self._autonomy_manager:
            # Would trigger learning cycle
            pass

        return result

    def _build_decision_context(
        self,
        pipeline_context: DecisionPipelineContext,
        action: Dict[str, Any]
    ):
        """Build DecisionContext from pipeline context and action."""
        from app.decision.models import DecisionContext
        return DecisionContext(
            task_description=action.get("description", ""),
            component="unified_pipeline",
            active_goal_id=pipeline_context.active_goals[0].get("id") if pipeline_context.active_goals else None,
            metadata={
                "action_type": action.get("type"),
                "action_priority": action.get("priority"),
                "system_health": pipeline_context.system_health,
                "health_score": pipeline_context.health_score,
                "resource_cpu": pipeline_context.cpu_percent,
                "resource_memory": pipeline_context.memory_percent,
                "active_alerts": len(pipeline_context.active_alerts),
                **action.get("metadata", {}),
            }
        )

    # ============================================================
    # Event Handlers
    # ============================================================

    def _on_intent_executed(self, event: Event) -> None:
        pass  # Context updated on next pipeline run

    def _on_workflow_completed(self, event: Event) -> None:
        pass

    def _on_workflow_failed(self, event: Event) -> None:
        pass

    def _on_decision_made(self, event: Event) -> None:
        pass

    def _on_recovery_started(self, event: Event) -> None:
        pass

    def _on_recovery_completed(self, event: Event) -> None:
        pass

    def _on_autonomy_cycle(self, event: Event) -> None:
        pass

    # ============================================================
    # Public API
    # ============================================================

    def get_latest_result(self) -> Optional[DecisionPipelineResult]:
        """Get the most recent pipeline result."""
        with self._lock:
            return self._pipeline_history[-1] if self._pipeline_history else None

    def get_history(self, limit: int = 10) -> List[DecisionPipelineResult]:
        """Get pipeline execution history."""
        with self._lock:
            return self._pipeline_history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        with self._lock:
            total = len(self._pipeline_history)
            if total == 0:
                return {"total_runs": 0}

            successful = sum(1 for r in self._pipeline_history if r.chosen_action is not None)
            avg_time = sum(r.context.collection_time_ms for r in self._pipeline_history) / total

            return {
                "total_runs": total,
                "successful_decisions": successful,
                "success_rate": successful / total if total > 0 else 0,
                "avg_collection_time_ms": avg_time,
                "last_run": self._pipeline_history[-1].timestamp if self._pipeline_history else None,
            }


# Global instance
_unified_pipeline: Optional[UnifiedRuntimeDecisionPipeline] = None
_pipeline_lock = threading.Lock()


def get_unified_pipeline(
    orchestrator: "Optional[CentralOrchestrator]" = None,
    decision_manager: Optional[DecisionManager] = None,
    world_model: Optional[WorldModel] = None,
    memory_retrieval: Optional[UnifiedRetrieval] = None,
    failure_recovery: Optional[RecoveryOrchestrator] = None,
    autonomy_manager: Optional[AutonomyManager] = None,
) -> UnifiedRuntimeDecisionPipeline:
    """Get or create the global unified pipeline instance."""
    global _unified_pipeline
    with _pipeline_lock:
        if _unified_pipeline is None:
            _unified_pipeline = UnifiedRuntimeDecisionPipeline(
                orchestrator=orchestrator,
                decision_manager=decision_manager,
                world_model=world_model,
                memory_retrieval=memory_retrieval,
                failure_recovery=failure_recovery,
                autonomy_manager=autonomy_manager,
            )
        return _unified_pipeline


def set_unified_pipeline(pipeline: UnifiedRuntimeDecisionPipeline) -> None:
    """Set the global unified pipeline instance."""
    global _unified_pipeline
    with _pipeline_lock:
        _unified_pipeline = pipeline