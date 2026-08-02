"""Decision Manager - Central orchestrator for Freya's decision-making.

This module implements the DecisionManager class which coordinates the complete
decision workflow: Observe → Gather Context → Identify Actions → Evaluate Options
→ Estimate Risk/Benefit → Choose Best → Execute → Observe Outcome → Learn.

It integrates with existing systems:
- Confidence Scoring (app/confidence/)
- Risk Assessment (app/risk/)
- Goal Scheduling (app/memory/goals.py)
- Planning (app/agent/planner.py, app/planner/plan_manager.py)
- Memory Retrieval (app/memory/unified_retrieval.py)
- Intent Classification (app/intent/classifier.py)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import logging
import uuid

from app.decision.models import (
    DecisionCategory,
    DecisionType,
    DecisionContext,
    DecisionOption,
    DecisionResult,
    DecisionRecord,
    DecisionManagerConfig,
)
from app.decision.workflow import DecisionWorkflow, WorkflowStep
from app.decision.history import DecisionHistory

# Shared infrastructure imports
from app.core.events import get_event_bus, EventBus, Event
from app.core.background_jobs import get_job_service, BackgroundJobService
from app.core.observability import get_observability_hub, ObservabilityHub, ComponentInfo, ComponentType

# Optional imports for integration with existing systems
try:
    from app.confidence.confidence_model import ConfidenceModel, DecisionConfidence, ActionConfidence
    from app.confidence.confidence_scoring import ConfidenceCalculator, ConfidenceLevel
except ImportError:
    ConfidenceModel = None
    DecisionConfidence = None
    ActionConfidence = None
    ConfidenceCalculator = None
    ConfidenceLevel = None

try:
    from app.risk.risk_analyzer import RiskAnalyzer
    from app.risk.risk_item import RiskItem, RiskSeverity, RiskProbability
except ImportError:
    RiskAnalyzer = None
    RiskItem = None
    RiskSeverity = None
    RiskProbability = None

try:
    from app.memory.goals import GoalStorage
except ImportError:
    GoalStorage = None

try:
    from app.memory.unified_retrieval import UnifiedRetrieval, RetrievalQuery
except ImportError:
    UnifiedRetrieval = None
    RetrievalQuery = None

try:
    from app.intent.classifier import classify_intent, IntentType, IntentClassification
except ImportError:
    classify_intent = None
    IntentType = None
    IntentClassification = None

try:
    from app.agent.planner import Planner
    from app.planner.plan_manager import PlanManager
except ImportError:
    Planner = None
    PlanManager = None

logger = logging.getLogger(__name__)


# Type alias for decision handlers
DecisionHandler = Callable[[DecisionContext, List[DecisionOption]], DecisionResult]


class DecisionManager:
    """Central Decision Manager orchestrating the complete decision workflow.

    The DecisionManager is the single entry point for all significant decisions
    in Freya. It coordinates existing systems (confidence, risk, goals, planning,
    memory, intent) into a unified workflow.

    Usage:
        manager = DecisionManager(workspace=".")
        result = manager.decide(context, options)
    """

    def __init__(
        self,
        workspace: str = ".",
        config: Optional[DecisionManagerConfig] = None,
        # Injected dependencies (for testing and flexibility)
        confidence_calculator: Optional[Any] = None,
        risk_analyzer: Optional[Any] = None,
        goal_storage: Optional[Any] = None,
        unified_retrieval: Optional[Any] = None,
        intent_classifier: Optional[Callable] = None,
        planner: Optional[Any] = None,
        plan_manager: Optional[Any] = None,
        decision_history: Optional[DecisionHistory] = None,
        # Shared infrastructure
        event_bus: Optional[EventBus] = None,
        job_service: Optional[BackgroundJobService] = None,
        observability: Optional[ObservabilityHub] = None,
    ):
        """Initialize the Decision Manager.

        Args:
            workspace: Workspace path for persistence
            config: Configuration object
            confidence_calculator: Optional ConfidenceCalculator instance
            risk_analyzer: Optional RiskAnalyzer instance
            goal_storage: Optional GoalStorage instance
            unified_retrieval: Optional UnifiedRetrieval instance
            intent_classifier: Optional intent classification function
            planner: Optional Planner instance
            plan_manager: Optional PlanManager instance
            decision_history: Optional DecisionHistory instance
            event_bus: Optional shared EventBus instance
            job_service: Optional shared BackgroundJobService instance
            observability: Optional shared ObservabilityHub instance
        """
        self.workspace = workspace
        self.config = config or DecisionManagerConfig()

        # Shared infrastructure
        self.event_bus = event_bus or get_event_bus()
        self.job_service = job_service or get_job_service()
        self.observability = observability or get_observability_hub()

        # Injected dependencies (use provided or create defaults)
        self._confidence_calculator = confidence_calculator
        self._risk_analyzer = risk_analyzer
        self._goal_storage = goal_storage
        self._unified_retrieval = unified_retrieval
        self._intent_classifier = intent_classifier
        self._planner = planner
        self._plan_manager = plan_manager

        # Core components
        self.workflow = DecisionWorkflow()
        self.history = decision_history or DecisionHistory(workspace)

        # Decision handlers registry (category -> handler)
        self._handlers: Dict[DecisionCategory, DecisionHandler] = {}
        self._register_default_handlers()

        # Statistics
        self._stats = {
            "total_decisions": 0,
            "decisions_by_category": {},
            "decisions_by_type": {},
            "auto_executed": 0,
            "human_review_required": 0,
            "confidence_calibrations": 0,
        }

        # Phase 2+ Enhancement Components (lazy-initialized to avoid circular imports)
        self._adaptive_revision: Optional[Any] = None
        self._learning_from_decisions: Optional[Any] = None
        self._visualization: Optional[Any] = None
        self._meta_learning: Optional[Any] = None
        self._human_oversight: Optional[Any] = None

        # Initialize Phase 2+ capabilities
        self._init_phase2_capabilities()

        # Register with observability
        self._register_with_observability()

        logger.info(f"DecisionManager initialized with workspace: {workspace}")

    def _register_default_handlers(self) -> None:
        """Register default decision handlers for each category."""
        self._handlers[DecisionCategory.EXECUTION] = self._handle_execution_decision
        self._handlers[DecisionCategory.INFORMATION] = self._handle_information_decision
        self._handlers[DecisionCategory.PLANNING] = self._handle_planning_decision
        self._handlers[DecisionCategory.RECOVERY] = self._handle_recovery_decision
        self._handlers[DecisionCategory.LEARNING] = self._handle_learning_decision

    def _register_with_observability(self) -> None:
        """Register this subsystem with the shared ObservabilityHub."""
        if self.observability and hasattr(self.observability, 'health_monitor'):
            self.observability.health_monitor.register_check(
                "decision_manager",
                self._health_check,
                interval_seconds=30.0,
            )

            # Register component
            self.observability.register_component(ComponentInfo(
                name="DecisionManager",
                component_type=ComponentType.AGENT,
                version="1.0.0",
                description="Central decision orchestration",
                metadata={"workspace": self.workspace},
            ))

    def _health_check(self):
        """Health check for DecisionManager."""
        from app.core.observability import HealthCheckResult, HealthStatus
        try:
            return HealthCheckResult(
                component="decision_manager",
                status=HealthStatus.HEALTHY,
                message="DecisionManager operational",
                metadata={"total_decisions": self._stats["total_decisions"]}
            )
        except Exception as e:
            return HealthCheckResult(
                component="decision_manager",
                status=HealthStatus.CRITICAL,
                message=f"Health check failed: {e}",
                metadata={"error": str(e)}
            )

    def _publish_event(self, event_name: str, data: Dict[str, Any]) -> None:
        """Publish an event to the shared EventBus."""
        try:
            event = Event(
                name=event_name,
                data=data,
                source="DecisionManager"
            )
            self.event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Failed to publish event {event_name}: {e}")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def decide(
        self,
        context: DecisionContext,
        options: List[DecisionOption],
    ) -> DecisionResult:
        """Main decision entry point - runs the complete decision workflow.

        This is the primary method for making decisions. It:
        1. Observes the situation from context
        2. Gathers additional context from memory/goals/intent
        3. Identifies/validates available actions (options)
        4. Evaluates each option with confidence and risk
        5. Chooses the best option
        6. Returns a DecisionResult with recommendation

        Args:
            context: DecisionContext with all relevant situational information
            options: List of DecisionOption representing available choices

        Returns:
            DecisionResult with chosen option, confidence, risk, and rationale
        """
        # Get decision type from first option
        decision_type = options[0].decision_type if options else DecisionType.TOOL_SELECTION
        logger.info(f"[DecisionManager] Starting decision for {decision_type.value} in {context.component}")

        # Run the workflow
        result = self.workflow.execute(
            context=context,
            options=options,
            confidence_calculator=self._get_confidence_calculator(),
            risk_analyzer=self._get_risk_analyzer(),
            goal_storage=self._get_goal_storage(),
            unified_retrieval=self._get_unified_retrieval(),
            intent_classifier=self._get_intent_classifier(),
            planner=self._get_planner(),
            config=self.config,
        )

        # Apply category-specific handling
        handler = self._handlers.get(result.category)
        if handler:
            result = handler(context, result)

        # Enhance with Phase 2+ capabilities
        result = self._enhance_result_with_phase2(context, result)

        # Record decision if enabled
        if self.config.record_all_decisions:
            self._record_decision(context, result)

        # Update statistics
        self._update_stats(result)

        # Publish decision event
        self._publish_event("decision.made", {
            "decision_id": result.decision_id,
            "type": result.decision_type.value,
            "category": result.category.value,
            "chosen_option": result.chosen_option.name if result.chosen_option else None,
            "confidence": result.confidence,
            "risk_level": result.risk_level,
            "should_execute": result.should_execute,
            "requires_approval": result.requires_approval,
            "component": context.component,
        })

        logger.info(
            f"[DecisionManager] Decision complete: {result.chosen_option.name if result.chosen_option else 'none'} "
            f"(confidence={result.confidence:.2f}, risk={result.risk_level}, "
            f"auto_execute={result.should_execute})"
        )

        return result

    def decide_simple(
        self,
        decision_type: DecisionType,
        task_description: str,
        options: List[DecisionOption],
        component: str = "freya_agent",
        **context_kwargs,
    ) -> DecisionResult:
        """Simplified decision interface for common cases.

        Args:
            decision_type: Type of decision being made
            task_description: Human-readable description of the task
            options: Available options to choose from
            component: Component making the decision
            **context_kwargs: Additional context fields

        Returns:
            DecisionResult
        """
        context = DecisionContext(
            task_description=task_description,
            component=component,
            **context_kwargs,
        )
        return self.decide(context, options)

    def register_handler(
        self,
        category: DecisionCategory,
        handler: DecisionHandler,
    ) -> None:
        """Register a custom decision handler for a category.

        Args:
            category: Decision category to handle
            handler: Function taking (context, result) and returning enhanced result
        """
        self._handlers[category] = handler
        logger.info(f"[DecisionManager] Registered custom handler for {category.value}")

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        outcome_details: str = "",
        actual_success: Optional[bool] = None,
        actual_effort: Optional[float] = None,
        actual_impact: Optional[float] = None,
        error: Optional[str] = None,
        lesson_learned: str = "",
        would_repeat: Optional[bool] = None,
    ) -> None:
        """Record the actual outcome of a decision for learning.

        This closes the loop: decision → execution → outcome → learning.

        Args:
            decision_id: ID of the decision (from DecisionResult.decision_id)
            outcome: Outcome category (success, partial, failure, aborted)
            outcome_details: Human-readable description of what happened
            actual_success: Whether the action actually succeeded
            actual_effort: Actual effort (0.0-1.0, relative to estimate)
            actual_impact: Actual impact (0.0-1.0)
            error: Error message if failed
            lesson_learned: What was learned from this outcome
            would_repeat: Whether we'd make the same decision again
        """
        self.history.record_outcome(
            decision_id=decision_id,
            outcome=outcome,
            outcome_details=outcome_details,
            actual_success=actual_success,
            actual_effort=actual_effort,
            actual_impact=actual_impact,
            error=error,
            lesson_learned=lesson_learned,
            would_repeat=would_repeat,
        )

        # Calibrate confidence models if enabled
        if self.config.calibrate_confidence_from_outcomes and actual_success is not None:
            self._calibrate_confidence(decision_id, actual_success, result.confidence if (result := self.history.get_decision(decision_id)) else 0.5)

        logger.info(f"[DecisionManager] Recorded outcome for {decision_id}: {outcome}")

    def explain_decision(self, result: DecisionResult) -> str:
        """Generate a human-readable explanation of a decision.

        Args:
            result: The DecisionResult to explain

        Returns:
            Plain English explanation
        """
        if not self.config.enable_explainable_decisions:
            return "Decision explanation disabled."

        lines = [
            f"Decision: {result.chosen_option.name if result.chosen_option else 'None chosen'}",
            f"Category: {result.category.value}",
            f"Type: {result.decision_type.value}",
            f"Confidence: {result.confidence:.0%} ({result.confidence_level})",
            f"Risk: {result.risk_level}",
            "",
            f"Rationale: {result.rationale}",
        ]

        if result.key_factors:
            lines.append("")
            lines.append("Key factors:")
            for factor in result.key_factors:
                lines.append(f"  • {factor}")

        if result.alternatives_considered:
            lines.append("")
            lines.append("Alternatives considered:")
            for alt in result.alternatives_considered[:3]:  # Top 3
                lines.append(f"  • {alt.name} (confidence: {alt.confidence_score:.0%})")

        if result.should_execute and not result.requires_approval:
            lines.append("")
            lines.append("→ Recommendation: PROCEED AUTOMATICALLY")
        elif result.requires_approval:
            lines.append("")
            lines.append("→ Recommendation: REQUIRES HUMAN APPROVAL")
        else:
            lines.append("")
            lines.append("→ Recommendation: PROCEED WITH CAUTION")

        return "\n".join(lines)

    def get_decision_history(
        self,
        decision_type: Optional[DecisionType] = None,
        category: Optional[DecisionCategory] = None,
        component: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> List[DecisionRecord]:
        """Query decision history with filters.

        Args:
            decision_type: Filter by decision type
            category: Filter by decision category
            component: Filter by component
            outcome: Filter by outcome
            since: ISO timestamp - decisions after this time
            until: ISO timestamp - decisions before this time
            limit: Maximum results to return

        Returns:
            List of DecisionRecord matching filters
        """
        return self.history.query(
            decision_type=decision_type,
            category=category,
            component=component,
            outcome=outcome,
            since=since,
            until=until,
            limit=limit,
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Get decision-making statistics.

        Returns:
            Dictionary with statistics
        """
        stats = self._stats.copy()
        stats["history"] = self.history.get_summary()
        return stats

    # -------------------------------------------------------------------------
    # Phase 2+ Enhancement Accessors
    # -------------------------------------------------------------------------

    @property
    def adaptive_revision(self) -> Optional[Any]:
        """Get the Adaptive Decision Revision component."""
        return self._adaptive_revision

    @property
    def learning_from_decisions(self) -> Optional[Any]:
        """Get the Learning From Decisions component."""
        return self._learning_from_decisions

    @property
    def visualization(self) -> Optional[Any]:
        """Get the Decision Visualization component."""
        return self._visualization

    @property
    def meta_learning(self) -> Optional[Any]:
        """Get the Meta-Decision Learning component."""
        return self._meta_learning

    @property
    def human_oversight(self) -> Optional[Any]:
        """Get the Human Oversight Manager component."""
        return self._human_oversight

    # -------------------------------------------------------------------------
    # Phase 2+ Enhancement Public Methods
    # -------------------------------------------------------------------------

    def start_adaptive_monitoring(self, context_provider: Callable[[], DecisionContext]) -> None:
        """Start background adaptive decision monitoring.

        Args:
            context_provider: Function that returns current DecisionContext
        """
        if self._adaptive_revision:
            self._adaptive_revision.start_monitoring(context_provider)
            logger.info("[DecisionManager] Started adaptive decision monitoring")
        else:
            logger.warning("[DecisionManager] Adaptive revision not available")

    def stop_adaptive_monitoring(self) -> None:
        """Stop background adaptive decision monitoring."""
        if self._adaptive_revision:
            self._adaptive_revision.stop_monitoring()
            logger.info("[DecisionManager] Stopped adaptive decision monitoring")

    def run_learning_analysis(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Run learning analysis on decision outcomes.

        Args:
            force_refresh: Force re-analysis of all records

        Returns:
            Analysis results
        """
        if self._learning_from_decisions:
            return self._learning_from_decisions.analyze_outcomes(force_refresh=force_refresh)
        return {"error": "Learning from decisions not available"}

    def run_meta_analysis(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Run meta-decision learning analysis.

        Args:
            force_refresh: Force re-analysis of all records

        Returns:
            Analysis results
        """
        if self._meta_learning:
            return self._meta_learning.analyze(force_refresh=force_refresh)
        return {"error": "Meta-decision learning not available"}

    def get_meta_confidence(
        self,
        decision_type: DecisionType,
        predicted_confidence: float,
        context: Dict[str, Any],
    ) -> Tuple[float, float, str]:
        """Get meta-confidence for a confidence estimate.

        Returns:
            Tuple of (meta_confidence, adjusted_confidence, explanation)
        """
        if self._meta_learning:
            return self._meta_learning.get_meta_confidence(decision_type, predicted_confidence, context)
        return 0.5, predicted_confidence, "Meta-learning not available"

    def should_require_human_approval(
        self,
        decision_type: DecisionType,
        risk_level: str,
        confidence: float,
        context: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Determine if human approval is required (with meta-learning)."""
        if self._meta_learning:
            return self._meta_learning.should_require_human_approval(decision_type, risk_level, confidence, context)

        # Fallback to default logic
        requires = risk_level in ("critical", "high") or confidence < 0.5
        reason = []
        if risk_level in ("critical", "high"):
            reason.append(f"risk level {risk_level}")
        if confidence < 0.5:
            reason.append(f"low confidence {confidence:.0%}")
        return requires, "; ".join(reason) if reason else "No approval required"

    def export_decision_graph(
        self,
        decision_ids: Optional[List[str]] = None,
        formats: List[str] = None,
    ) -> Dict[str, str]:
        """Export decision graph visualization.

        Args:
            decision_ids: Optional list of decision IDs to visualize
            formats: List of formats (dot, mermaid, json, html)

        Returns:
            Dict mapping format to output file path
        """
        if not self._visualization:
            return {"error": "Visualization not available"}

        formats = formats or ["dot", "mermaid", "json", "html"]
        return self._visualization.export_all_formats(decision_ids, formats=formats)

    def export_decision_timeline(
        self,
        decision_ids: Optional[List[str]] = None,
        formats: List[str] = None,
    ) -> Dict[str, str]:
        """Export decision timeline visualization.

        Args:
            decision_ids: Optional list of decision IDs to visualize
            formats: List of formats (json, mermaid)

        Returns:
            Dict mapping format to output file path
        """
        if not self._visualization:
            return {"error": "Visualization not available"}

        formats = formats or ["json", "mermaid"]
        events = self._visualization.build_timeline(decision_ids)
        results = {}
        if "json" in formats:
            results["json"] = self._visualization.export_timeline_json(events)
        if "mermaid" in formats:
            results["mermaid"] = self._visualization.export_timeline_mermaid(events)
        return results

    def request_human_approval(
        self,
        decision_id: str,
        decision_type: DecisionType,
        risk_level: str,
        confidence: float,
        title: str,
        description: str,
        options: List[DecisionOption],
        recommended_option: Optional[DecisionOption] = None,
        context: Optional[Dict[str, Any]] = None,
        priority: Any = None,
    ) -> Optional[Any]:
        """Request human approval for a decision.

        Args:
            decision_id: ID of the decision
            decision_type: Type of decision
            risk_level: Risk level
            confidence: Confidence in recommendation
            title: Short title
            description: Detailed description
            options: Available options
            recommended_option: Recommended option
            context: Additional context
            priority: Request priority

        Returns:
            ApprovalRequest if created, None if oversight not available
        """
        # Handle priority lazily
        if priority is None:
            try:
                from app.decision.human_oversight import ApprovalPriority
                priority = getattr(ApprovalPriority, 'NORMAL', 'normal')
            except ImportError:
                priority = 'normal'

        if not self._human_oversight:
            return None

        return self._human_oversight.request_approval(
            decision_id=decision_id,
            decision_type=decision_type,
            risk_level=risk_level,
            confidence=confidence,
            title=title,
            description=description,
            options=options,
            recommended_option=recommended_option,
            context=context or {},
            priority=priority,
        )

    def get_pending_approvals(self) -> List[Any]:
        """Get all pending approval requests."""
        if self._human_oversight:
            return self._human_oversight.get_pending_requests()
        return []

    def run_approval_ui(self) -> None:
        """Run the interactive approval UI."""
        if self._human_oversight:
            self._human_oversight.run_approval_ui()
        else:
            logger.warning("[DecisionManager] Human oversight not available")

    def review_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        """Review a decision and its approval history."""
        if self._human_oversight:
            return self._human_oversight.review_decision(decision_id)
        return None

    def override_decision(
        self,
        decision_id: str,
        new_option: DecisionOption,
        reason: str,
        overridden_by: str = "user",
    ) -> bool:
        """Override a decision's chosen option."""
        if self._human_oversight:
            return self._human_oversight.override_decision(decision_id, new_option, reason, overridden_by)
        return False

    def get_audit_log(
        self,
        decision_id: Optional[str] = None,
        action_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get audit log entries."""
        if self._human_oversight:
            return self._human_oversight.get_audit_log(decision_id, action_type, limit)
        return []

    # -------------------------------------------------------------------------
    # Enhanced Decision Workflow Integration
    # -------------------------------------------------------------------------

    def _enhance_result_with_phase2(self, context: DecisionContext, result: DecisionResult) -> DecisionResult:
        """Enhance decision result with Phase 2+ capabilities."""
        # Apply learning-based confidence adjustment
        if self._learning_from_decisions:
            adjustment, explanation = self._learning_from_decisions.get_confidence_adjustment(
                result.decision_type,
                {
                    "risk_level": result.risk_level,
                    "component": context.component,
                    **context.metadata,
                },
            )
            if adjustment != 1.0:
                original_confidence = result.confidence
                result.confidence = max(0.0, min(1.0, result.confidence * adjustment))
                result.confidence_level = self._confidence_level_from_score(result.confidence)
                result.rationale += f" [Learning adjustment: {explanation}]"

        # Apply meta-learning confidence adjustment
        if self._meta_learning:
            meta_conf, adjusted_conf, meta_explanation = self._meta_learning.get_meta_confidence(
                result.decision_type,
                result.confidence,
                {
                    "risk_level": result.risk_level,
                    "component": context.component,
                    **context.metadata,
                },
            )
            if meta_conf < 0.5:
                result.rationale += f" [Low meta-confidence: {meta_explanation}]"
            result.confidence = adjusted_conf
            result.confidence_level = self._confidence_level_from_score(result.confidence)

        # Check if human approval required (enhanced with meta-learning)
        if self.config.enable_human_oversight and self._meta_learning:
            requires_approval, reason = self.should_require_human_approval(
                result.decision_type,
                result.risk_level,
                result.confidence,
                {
                    "risk_level": result.risk_level,
                    "component": context.component,
                    **context.metadata,
                },
            )
            if requires_approval:
                result.requires_approval = True
                result.should_execute = False
                result.rationale += f" [Meta-learning: {reason}]"

        # Register for adaptive monitoring if significant decision
        if (self._adaptive_revision and
            result.risk_level in ("high", "critical") and
            result.confidence > 0.5):
            self._adaptive_revision.register_decision_for_monitoring(
                decision_id=result.decision_id,
                context=context,
                max_revisions=3,
            )

        return result

    def calibrate_confidence(
        self,
        decision_id: str,
        actual_outcome: bool,
    ) -> float:
        """Manually calibrate confidence based on actual outcome.

        Args:
            decision_id: ID of the decision
            actual_outcome: Whether the decision led to success (True) or failure (False)

        Returns:
            Calibration adjustment applied
        """
        record = self.history.get_decision(decision_id)
        if not record:
            return 0.0

        predicted = record.confidence
        calibration = 1.0 - abs(predicted - (1.0 if actual_outcome else 0.0))
        record.confidence_calibration = calibration
        self.history.update_record(record)

        self._stats["confidence_calibrations"] += 1
        logger.info(f"[DecisionManager] Calibrated decision {decision_id}: predicted={predicted:.2f}, actual={'success' if actual_outcome else 'failure'}, calibration={calibration:.2f}")

        return calibration

    # -------------------------------------------------------------------------
    # Category-specific handlers
    # -------------------------------------------------------------------------

    def _handle_execution_decision(
        self,
        context: DecisionContext,
        result: DecisionResult,
    ) -> DecisionResult:
        """Handle execution category decisions (tool selection, file mods, commands)."""
        # Execution decisions with high risk need explicit approval
        if result.risk_level in ("critical", "high") and self.config.enable_human_oversight:
            result.requires_approval = True
            result.should_execute = False
            result.rationale += " [HIGH RISK - Human approval required]"

        # Low confidence + execution = needs review
        if result.confidence < self.config.min_confidence_for_auto_execute:
            result.should_execute = False
            if result.confidence < self.config.min_confidence_for_recommendation:
                result.requires_approval = True
                result.rationale += " [LOW CONFIDENCE - Human review recommended]"

        return result

    def _handle_information_decision(
        self,
        context: DecisionContext,
        result: DecisionResult,
    ) -> DecisionResult:
        """Handle information gathering decisions (context sufficiency, memory retrieval)."""
        # Information decisions are generally low risk
        # Auto-execute if confidence is reasonable
        if result.confidence >= self.config.min_confidence_for_recommendation:
            result.should_execute = True
        else:
            result.should_execute = False
            result.rationale += " [Low confidence in information need - consider skipping]"

        return result

    def _handle_planning_decision(
        self,
        context: DecisionContext,
        result: DecisionResult,
    ) -> DecisionResult:
        """Handle planning decisions (decomposition, strategy, priority, resources)."""
        # Planning decisions affect downstream work - be more cautious
        if result.risk_level in ("critical", "high"):
            result.requires_approval = True
            result.should_execute = False

        # If we're replanning after failure, be more conservative
        if context.metadata.get("is_replan", False):
            result.confidence *= 0.9  # Slight penalty for replanning
            result.confidence_level = (
                self._get_confidence_calculator().__class__.ConfidenceLevel.from_score(result.confidence)
                if self._get_confidence_calculator() and hasattr(self._get_confidence_calculator(), 'ConfidenceLevel')
                else self._confidence_level_from_score(result.confidence)
            )
            result.rationale += " [Replanning context - adjusted confidence]"

        return result

    def _handle_recovery_decision(
        self,
        context: DecisionContext,
        result: DecisionResult,
    ) -> DecisionResult:
        """Handle recovery decisions (retry, alternative, pause, abort, escalate)."""
        # Recovery decisions are critical - usually need human oversight for high stakes
        if result.risk_level in ("critical", "high"):
            result.requires_approval = True
            result.should_execute = False

        # Escalate/abort always need approval
        if result.chosen_option and result.chosen_option.decision_type in (
            DecisionType.ESCALATE,
            DecisionType.ABORT_TASK,
        ):
            result.requires_approval = True
            result.should_execute = False

        # Prefer alternatives with proven track record
        for alt in result.alternatives_considered:
            if alt.metadata.get("historical_success_rate", 0) > 0.8:
                alt.confidence_score *= 1.1  # Boost proven alternatives

        return result

    def _handle_learning_decision(
        self,
        context: DecisionContext,
        result: DecisionResult,
    ) -> DecisionResult:
        """Handle learning decisions (store lesson, experience, consolidate)."""
        # Learning decisions are low risk, usually auto-execute
        result.should_execute = True
        result.requires_approval = False

        # Boost confidence for high-value learning
        if result.chosen_option and result.chosen_option.metadata.get("value_score", 0) > 0.7:
            result.confidence = min(1.0, result.confidence * 1.1)
            result.confidence_level = self._confidence_level_from_score(result.confidence)

        return result

    # -------------------------------------------------------------------------
    # Integration helpers (lazy initialization)
    # -------------------------------------------------------------------------

    def _get_confidence_calculator(self):
        """Get or create confidence calculator."""
        if self._confidence_calculator is None and ConfidenceCalculator:
            self._confidence_calculator = ConfidenceCalculator()
        return self._confidence_calculator

    def _get_risk_analyzer(self):
        """Get or create risk analyzer."""
        if self._risk_analyzer is None and RiskAnalyzer:
            self._risk_analyzer = RiskAnalyzer()
        return self._risk_analyzer

    def _get_goal_storage(self):
        """Get or create goal storage."""
        if self._goal_storage is None and GoalStorage:
            self._goal_storage = GoalStorage(self.workspace)
        return self._goal_storage

    def _get_unified_retrieval(self):
        """Get or create unified retrieval."""
        if self._unified_retrieval is None and UnifiedRetrieval:
            # This would need an agent reference - use standalone for now
            pass
        return self._unified_retrieval

    def _get_intent_classifier(self):
        """Get intent classifier function."""
        return self._intent_classifier or classify_intent

    def _get_planner(self):
        """Get planner instance."""
        return self._planner

    def _get_plan_manager(self):
        """Get plan manager instance."""
        return self._plan_manager

    def _confidence_level_from_score(self, score: float):
        """Convert score to confidence level."""
        try:
            from app.confidence.confidence_scoring import ConfidenceLevel as CL
            return CL.from_score(score).value
        except ImportError:
            if score >= 0.8:
                return "very_high"
            elif score >= 0.6:
                return "high"
            elif score >= 0.4:
                return "medium"
            elif score >= 0.2:
                return "low"
            return "critical"

    # -------------------------------------------------------------------------
    # Recording and statistics
    # -------------------------------------------------------------------------

    def _record_decision(self, context: DecisionContext, result: DecisionResult) -> None:
        """Record decision to history."""
        record = DecisionRecord.from_result(result, context)
        # Store alternatives in metadata for visualization
        if result.alternatives_considered:
            record.metadata["alternatives_considered"] = [
                {"name": opt.name, "action": opt.action, "description": opt.description}
                for opt in result.alternatives_considered
            ]
        # Store revision info if applicable
        if result.metadata.get("is_revision"):
            record.metadata["is_revision"] = True
            record.metadata["original_decision_id"] = result.metadata.get("original_decision_id")
            record.metadata["trigger_changes"] = result.metadata.get("trigger_changes", [])
        self.history.add_record(record)

    def _update_stats(self, result: DecisionResult) -> None:
        """Update decision statistics."""
        self._stats["total_decisions"] += 1

        cat = result.category.value
        self._stats["decisions_by_category"][cat] = self._stats["decisions_by_category"].get(cat, 0) + 1

        typ = result.decision_type.value
        self._stats["decisions_by_type"][typ] = self._stats["decisions_by_type"].get(typ, 0) + 1

        if result.should_execute and not result.requires_approval:
            self._stats["auto_executed"] += 1
        if result.requires_approval:
            self._stats["human_review_required"] += 1

    def _calibrate_confidence(self, decision_id: str, actual_success: bool, predicted_confidence: float) -> None:
        """Calibrate confidence model based on outcome."""
        # This is a placeholder for more sophisticated calibration
        # In the future, this could update the confidence calculator's weights
        pass

    def _init_phase2_capabilities(self) -> None:
        """Initialize Phase 2+ enhancement capabilities."""
        # Lazy imports to avoid circular dependency
        try:
            from app.decision.adaptive_revision import AdaptiveDecisionRevision
            self._adaptive_revision = AdaptiveDecisionRevision(
                decision_manager=self,
                decision_history=self.history,
                check_interval_seconds=30.0,
                job_service=self.job_service,
            )
            logger.info("[DecisionManager] Adaptive Decision Revision initialized")
        except ImportError:
            logger.debug("[DecisionManager] Adaptive Decision Revision not available")

        try:
            from app.decision.learning import LearningFromDecisions
            calc = self._get_confidence_calculator()
            self._learning_from_decisions = LearningFromDecisions(
                decision_history=self.history,
                confidence_calculator=calc,
                workspace=self.workspace,
            )
            logger.info("[DecisionManager] Learning From Decisions initialized")
        except ImportError:
            logger.debug("[DecisionManager] Learning From Decisions not available")

        try:
            from app.decision.visualization import DecisionVisualization
            self._visualization = DecisionVisualization(
                decision_history=self.history,
                workspace=self.workspace,
            )
            logger.info("[DecisionManager] Decision Visualization initialized")
        except ImportError:
            logger.debug("[DecisionManager] Decision Visualization not available")

        try:
            from app.decision.meta_learning import MetaDecisionLearning
            calc = self._get_confidence_calculator()
            self._meta_learning = MetaDecisionLearning(
                decision_history=self.history,
                learning_from_decisions=self._learning_from_decisions,
                confidence_calculator=calc,
                workspace=self.workspace,
            )
            logger.info("[DecisionManager] Meta-Decision Learning initialized")
        except ImportError:
            logger.debug("[DecisionManager] Meta-Decision Learning not available")

        try:
            from app.decision.human_oversight import HumanOversightManager
            self._human_oversight = HumanOversightManager(
                decision_history=self.history,
                workspace=self.workspace,
                default_timeout_seconds=300.0,
                enable_ui=True,
            )
            logger.info("[DecisionManager] Human Oversight Manager initialized")
        except ImportError:
            logger.debug("[DecisionManager] Human Oversight not available")


# -------------------------------------------------------------------------
# Convenience functions for common decisions
# -------------------------------------------------------------------------

def decide_tool_selection(
    manager: DecisionManager,
    task: str,
    available_tools: List[str],
    context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Decide which tool to use for a task.

    Args:
        manager: DecisionManager instance
        task: Description of the task
        available_tools: List of available tool names
        context: Additional context

    Returns:
        DecisionResult with chosen tool
    """
    options = [
        DecisionOption(
            name=tool,
            action=f"use_{tool}",
            description=f"Use {tool} to accomplish: {task}",
            decision_type=DecisionType.TOOL_SELECTION,
            category=DecisionCategory.EXECUTION,
            estimated_success=0.7,
            estimated_effort=0.3,
            estimated_impact=0.5,
            metadata={"tool": tool, "task": task},
        )
        for tool in available_tools
    ]

    decision_context = DecisionContext(
        task_description=task,
        component="executor",
        active_goal_id=context.get("active_goal_id") if context else None,
        plan_id=context.get("plan_id") if context else None,
        metadata=context or {},
    )

    return manager.decide(decision_context, options)


def decide_context_sufficiency(
    manager: DecisionManager,
    task: str,
    current_context: str,
    intent_type: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Decide if current context is sufficient to proceed.

    Args:
        manager: DecisionManager instance
        task: Task description
        current_context: Currently gathered context
        intent_type: Intent classification if available
        context: Additional context

    Returns:
        DecisionResult indicating whether to proceed or gather more info
    """
    options = [
        DecisionOption(
            name="proceed",
            action="proceed_with_execution",
            description="Current context is sufficient, proceed with execution",
            decision_type=DecisionType.CONTEXT_SUFFICIENCY,
            category=DecisionCategory.INFORMATION,
            estimated_success=0.7,
            estimated_effort=0.1,
            estimated_impact=0.5,
            metadata={"context_length": len(current_context)},
        ),
        DecisionOption(
            name="gather_more",
            action="gather_more_context",
            description="Need more context - read files, search memory, ask user",
            decision_type=DecisionType.CONTEXT_SUFFICIENCY,
            category=DecisionCategory.INFORMATION,
            estimated_success=0.8,
            estimated_effort=0.4,
            estimated_impact=0.6,
            metadata={"context_length": len(current_context)},
        ),
    ]

    decision_context = DecisionContext(
        task_description=task,
        component="agent",
        available_context=current_context,
        metadata={"intent_type": intent_type, **(context or {})},
    )

    return manager.decide(decision_context, options)


def decide_recovery_action(
    manager: DecisionManager,
    task: str,
    failure_reason: str,
    attempt_number: int,
    max_attempts: int,
    context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Decide how to recover from a failure.

    Args:
        manager: DecisionManager instance
        task: Task that failed
        failure_reason: Description of the failure
        attempt_number: Current attempt number (1-indexed)
        max_attempts: Maximum attempts allowed
        context: Additional context

    Returns:
        DecisionResult with recovery action
    """
    options = [
        DecisionOption(
            name="retry_same",
            action="retry_same_approach",
            description="Retry the same approach",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.3,
            estimated_effort=0.3,
            estimated_impact=0.4,
            metadata={"attempt": attempt_number, "max_attempts": max_attempts},
        ),
        DecisionOption(
            name="try_alternative",
            action="try_alternative_approach",
            description="Try a different approach",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.6,
            estimated_effort=0.5,
            estimated_impact=0.7,
            metadata={"attempt": attempt_number, "max_attempts": max_attempts},
        ),
    ]

    # Add pause/ask option if not at max attempts
    if attempt_number < max_attempts:
        options.append(
            DecisionOption(
                name="pause_ask_user",
                action="pause_and_ask_user",
                description="Pause and ask user for guidance",
                decision_type=DecisionType.PAUSE_AND_ASK,
                category=DecisionCategory.RECOVERY,
                estimated_success=0.9,
                estimated_effort=0.1,
                estimated_impact=0.3,
                metadata={"attempt": attempt_number, "max_attempts": max_attempts},
            )
        )

    # Add abort option
    options.append(
        DecisionOption(
            name="abort",
            action="abort_task",
            description="Give up on this task",
            decision_type=DecisionType.ABORT_TASK,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.0,
            estimated_effort=0.0,
            estimated_impact=0.0,
            metadata={"attempt": attempt_number, "max_attempts": max_attempts},
        )
    )

    decision_context = DecisionContext(
        task_description=f"Recover from failure: {task}",
        component="agent",
        metadata={
            "failure_reason": failure_reason,
            "attempt_number": attempt_number,
            "max_attempts": max_attempts,
            **(context or {}),
        },
    )

    return manager.decide(decision_context, options)


def _decide_replanning_strategy_internal(
    manager: DecisionManager,
    failed_task: str,
    failure_context: str,
    original_task: str,
    additional_context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Internal implementation for replanning strategy decisions."""
    options = [
        DecisionOption(
            name="alternative_approach",
            action="try_alternative_approach",
            description="Try a completely different approach to achieve the goal",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.65,
            estimated_effort=0.5,
            estimated_impact=0.7,
            metadata={"failed_task": failed_task, "strategy": "alternative"},
        ),
        DecisionOption(
            name="decompose_further",
            action="decompose_into_smaller_steps",
            description="Break the failed task into smaller, more manageable steps",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.7,
            estimated_effort=0.4,
            estimated_impact=0.6,
            metadata={"failed_task": failed_task, "strategy": "decompose"},
        ),
        DecisionOption(
            name="retry_with_fix",
            action="retry_with_targeted_fix",
            description="Apply a targeted fix based on the failure reason and retry",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.55,
            estimated_effort=0.3,
            estimated_impact=0.5,
            metadata={"failed_task": failed_task, "strategy": "retry_with_fix"},
        ),
    ]

    decision_context = DecisionContext(
        task_description=f"Replan after failure: {failed_task}",
        component="planner",
        available_context=f"Original task: {original_task}\nFailed task: {failed_task}\nFailure context: {failure_context}",
        metadata={
            "failed_task": failed_task,
            "failure_context": failure_context,
            "original_task": original_task,
            "is_replan": True,
            **(additional_context or {}),
        },
    )

    return manager.decide(decision_context, options)


def decide_plan_approach(
    manager: DecisionManager,
    task: str,
    context: str,
    goal_id: Optional[str] = None,
    goal_name: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Decide on a planning approach for a goal execution.

    Args:
        manager: DecisionManager instance
        task: Task description
        context: Current context
        goal_id: Optional goal ID
        goal_name: Optional goal name
        additional_context: Additional context

    Returns:
        DecisionResult with planning guidance
    """
    return decide_planning_strategy(
        manager=manager,
        task=task,
        context=context,
        iteration=1,
        additional_context={
            "goal_id": goal_id,
            "goal_name": goal_name,
            **(additional_context or {}),
        },
    )


def decide_replanning_strategy(
    manager: DecisionManager,
    failed_task: str,
    failure_context: str,
    original_task: str,
    additional_context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Decide on a replanning strategy after a task failure.

    Args:
        manager: DecisionManager instance
        failed_task: Description of the failed task
        failure_context: Context about the failure
        original_task: Original task description
        additional_context: Additional context

    Returns:
        DecisionResult with replanning guidance
    """
    return _decide_replanning_strategy_internal(
        manager=manager,
        failed_task=failed_task,
        failure_context=failure_context,
        original_task=original_task,
        additional_context=additional_context,
    )


# Global default manager instance (lazy initialized)
_default_manager: Optional[DecisionManager] = None


def get_default_manager(workspace: str = ".") -> DecisionManager:
    """Get or create the default DecisionManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = DecisionManager(workspace=workspace)
    return _default_manager


def decide_planning_strategy(
    manager: DecisionManager,
    task: str,
    context: str,
    iteration: int = 1,
    previous_attempts: Optional[List[Dict[str, Any]]] = None,
    additional_context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Decide on a planning strategy for a task.

    Args:
        manager: DecisionManager instance
        task: Task description
        context: Current context
        iteration: Current iteration number
        previous_attempts: List of previous attempts with outcomes
        additional_context: Additional context

    Returns:
        DecisionResult with planning guidance
    """
    options = [
        DecisionOption(
            name="standard_planning",
            action="create_standard_plan",
            description="Create a standard sequential plan",
            decision_type=DecisionType.STRATEGY_SELECTION,
            category=DecisionCategory.PLANNING,
            estimated_success=0.7 if iteration == 1 else 0.5,
            estimated_effort=0.4,
            estimated_impact=0.6,
            metadata={"iteration": iteration, "strategy": "standard"},
        ),
        DecisionOption(
            name="adaptive_decomposition",
            action="decompose_adaptively",
            description="Break task into smaller adaptive steps based on context",
            decision_type=DecisionType.TASK_DECOMPOSITION,
            category=DecisionCategory.PLANNING,
            estimated_success=0.8,
            estimated_effort=0.5,
            estimated_impact=0.7,
            metadata={"iteration": iteration, "strategy": "adaptive"},
        ),
    ]

    if iteration > 1 and previous_attempts:
        options.append(
            DecisionOption(
                name="replan_with_lessons",
                action="replan_with_failure_lessons",
                description="Replan incorporating lessons from previous failures",
                decision_type=DecisionType.STRATEGY_SELECTION,
                category=DecisionCategory.PLANNING,
                estimated_success=0.75,
                estimated_effort=0.6,
                estimated_impact=0.8,
                metadata={"iteration": iteration, "strategy": "replan_with_lessons"},
            )
        )

    decision_context = DecisionContext(
        task_description=task,
        component="planner",
        available_context=context,
        metadata={
            "iteration": iteration,
            "previous_attempts": previous_attempts or [],
            **(additional_context or {}),
        },
    )

    return manager.decide(decision_context, options)


def decide_replanning_strategy(
    manager: DecisionManager,
    failed_task: str,
    failure_context: str,
    original_task: str,
    additional_context: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Decide on a replanning strategy after a task failure.

    Args:
        manager: DecisionManager instance
        failed_task: Description of the failed task
        failure_context: Context about the failure
        original_task: Original task description
        additional_context: Additional context

    Returns:
        DecisionResult with replanning guidance
    """
    options = [
        DecisionOption(
            name="alternative_approach",
            action="try_alternative_approach",
            description="Try a completely different approach to achieve the goal",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.65,
            estimated_effort=0.5,
            estimated_impact=0.7,
            metadata={"failed_task": failed_task, "strategy": "alternative"},
        ),
        DecisionOption(
            name="decompose_further",
            action="decompose_into_smaller_steps",
            description="Break the failed task into smaller, more manageable steps",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.7,
            estimated_effort=0.4,
            estimated_impact=0.6,
            metadata={"failed_task": failed_task, "strategy": "decompose"},
        ),
        DecisionOption(
            name="retry_with_fix",
            action="retry_with_targeted_fix",
            description="Apply a targeted fix based on the failure reason and retry",
            decision_type=DecisionType.RETRY_WITH_ALTERNATIVE,
            category=DecisionCategory.RECOVERY,
            estimated_success=0.55,
            estimated_effort=0.3,
            estimated_impact=0.5,
            metadata={"failed_task": failed_task, "strategy": "retry_with_fix"},
        ),
    ]

    decision_context = DecisionContext(
        task_description=f"Replan after failure: {failed_task}",
        component="planner",
        available_context=f"Original task: {original_task}\nFailed task: {failed_task}\nFailure context: {failure_context}",
        metadata={
            "failed_task": failed_task,
            "failure_context": failure_context,
            "original_task": original_task,
            "is_replan": True,
            **(additional_context or {}),
        },
    )

    return manager.decide(decision_context, options)