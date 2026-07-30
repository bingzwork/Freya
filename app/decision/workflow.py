"""Decision Workflow - Explicit pipeline for the decision process.

Implements the structured workflow:
Observe Situation → Gather Context → Identify Actions → Evaluate Options
→ Estimate Risk/Benefit → Choose Best Option → Execute → Observe Outcome → Next Decision

Each step is a separate stage that can be customized or extended.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
import logging

from app.decision.models import (
    DecisionCategory,
    DecisionType,
    DecisionContext,
    DecisionOption,
    DecisionResult,
    DecisionManagerConfig,
)

# Optional imports for integration
try:
    from app.confidence.confidence_model import DecisionConfidence, ActionConfidence, ConfidenceModel, ActionType
    from app.confidence.confidence_scoring import ConfidenceCalculator, ConfidenceLevel, ConfidenceEvent
except ImportError:
    ConfidenceCalculator = None
    ConfidenceLevel = None
    ConfidenceEvent = None
    ActionType = None

try:
    from app.risk.risk_analyzer import RiskAnalyzer
    from app.risk.risk_item import RiskItem, RiskSeverity, RiskProbability, RiskCategory
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
except ImportError:
    Planner = None

from app.decision.manager import DecisionManagerConfig

logger = logging.getLogger(__name__)


class WorkflowStep(str, Enum):
    """Enumeration of workflow step names."""
    OBSERVE = "observe"
    GATHER_CONTEXT = "gather_context"
    IDENTIFY_ACTIONS = "identify_actions"
    EVALUATE_OPTIONS = "evaluate_options"
    ESTIMATE_RISK_BENEFIT = "estimate_risk_benefit"
    CHOOSE_BEST = "choose_best"
    EXECUTE = "execute"
    LEARN_OUTCOME = "learn_outcome"


@dataclass
class WorkflowStepRecord:
    """A single executed step in the decision workflow."""
    name: str
    description: str
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    completed: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0


@dataclass
class WorkflowStepDefinition:
    """Definition of a workflow step (not an executed instance)."""
    name: str
    description: str


class DecisionWorkflow:
    """Orchestrates the complete decision workflow pipeline.

    The workflow consists of these stages:
    1. OBSERVE - Understand the current situation
    2. GATHER_CONTEXT - Collect relevant information from memory, goals, etc.
    3. IDENTIFY_ACTIONS - Generate/validate available options
    4. EVALUATE_OPTIONS - Score each option with confidence and risk
    5. ESTIMATE_RISK_BENEFIT - Combine risk and benefit estimates
    6. CHOOSE_BEST - Select the optimal option
    7. EXECUTE - Carry out the chosen action
    8. OBSERVE_OUTCOME - Record and learn from results
    """

    def __init__(self):
        self.steps: List[WorkflowStepDefinition] = [
            WorkflowStepDefinition(name=WorkflowStep.OBSERVE.value, description="Observe the current situation and decision type"),
            WorkflowStepDefinition(name=WorkflowStep.GATHER_CONTEXT.value, description="Gather relevant context from memory, goals, intent, and project state"),
            WorkflowStepDefinition(name=WorkflowStep.IDENTIFY_ACTIONS.value, description="Identify and validate available actions/options"),
            WorkflowStepDefinition(name=WorkflowStep.EVALUATE_OPTIONS.value, description="Evaluate each option with confidence scoring"),
            WorkflowStepDefinition(name=WorkflowStep.CHOOSE_BEST.value, description="Select the best option based on evaluation"),
            WorkflowStepDefinition(name=WorkflowStep.LEARN_OUTCOME.value, description="Record and learn from the outcome"),
        ]
        self._executed_steps: List[WorkflowStepRecord] = []
        self._step_handlers: Dict[str, Callable] = {
            "observe": self._step_observe,
            "gather_context": self._step_gather_context,
            "identify_actions": self._step_identify_actions,
            "evaluate_options": self._step_evaluate_options,
            "estimate_risk_benefit": self._step_estimate_risk_benefit,
            "choose_best": self._step_choose_best,
        }

    def execute(
        self,
        context: DecisionContext,
        options: List[DecisionOption],
        confidence_calculator: Optional[Any] = None,
        risk_analyzer: Optional[Any] = None,
        goal_storage: Optional[Any] = None,
        unified_retrieval: Optional[Any] = None,
        intent_classifier: Optional[Callable] = None,
        planner: Optional[Any] = None,
        config: Optional[DecisionManagerConfig] = None,
    ) -> DecisionResult:
        """Execute the complete decision workflow.

        Args:
            context: Decision context
            options: Available options to evaluate
            confidence_calculator: ConfidenceCalculator instance
            risk_analyzer: RiskAnalyzer instance
            goal_storage: GoalStorage instance
            unified_retrieval: UnifiedRetrieval instance
            intent_classifier: Intent classification function
            planner: Planner instance
            config: DecisionManager configuration

        Returns:
            DecisionResult with the chosen option and evaluation
        """
        self._executed_steps = []
        config = config or DecisionManagerConfig()

        # Workflow state passed between steps
        state = {
            "context": context,
            "options": options,
            "confidence_calculator": confidence_calculator,
            "risk_analyzer": risk_analyzer,
            "goal_storage": goal_storage,
            "unified_retrieval": unified_retrieval,
            "intent_classifier": intent_classifier,
            "planner": planner,
            "config": config,
            "enriched_context": {},
            "evaluated_options": [],
            "risk_assessments": {},
            "benefit_estimates": {},
            "chosen_option": None,
        }

        # Execute each step in sequence
        step_names = [
            "observe",
            "gather_context",
            "identify_actions",
            "evaluate_options",
            "estimate_risk_benefit",
            "choose_best",
        ]

        for step_name in step_names:
            handler = self._step_handlers.get(step_name)
            if handler:
                step = WorkflowStepRecord(
                    name=step_name,
                    description=self._step_description(step_name),
                    input_data={k: v for k, v in state.items() if k not in ["confidence_calculator", "risk_analyzer", "goal_storage", "unified_retrieval", "intent_classifier", "planner", "config"]},
                )
                start = datetime.now()
                handler(state)
                step.duration_ms = (datetime.now() - start).total_seconds() * 1000
                step.output_data = {k: v for k, v in state.items() if k not in ["confidence_calculator", "risk_analyzer", "goal_storage", "unified_retrieval", "intent_classifier", "planner", "config"]}
                step.completed = True
                self._executed_steps.append(step)
                logger.debug(f"[Workflow] Completed step: {step_name} ({step.duration_ms:.1f}ms)")

        # Build final result
        result = self._build_result(state)
        return result

    def _step_description(self, step_name: str) -> str:
        descriptions = {
            "observe": "Observe the current situation and decision type",
            "gather_context": "Gather relevant context from memory, goals, intent, and project state",
            "identify_actions": "Identify and validate available actions/options",
            "evaluate_options": "Evaluate each option with confidence scoring",
            "estimate_risk_benefit": "Estimate risk and benefit for each option",
            "choose_best": "Select the best option based on evaluation",
        }
        return descriptions.get(step_name, step_name)

    # -------------------------------------------------------------------------
    # Workflow Steps
    # -------------------------------------------------------------------------

    def _step_observe(self, state: Dict[str, Any]) -> None:
        """Step 1: Observe Situation - Understand what decision needs to be made."""
        context: DecisionContext = state["context"]
        options: List[DecisionOption] = state["options"]

        # Get decision type from first option or default
        decision_type = options[0].decision_type if options else DecisionType.TOOL_SELECTION

        logger.info(f"[Workflow] OBSERVE: {decision_type.value} in {context.component}")

        # Validate inputs
        if not options:
            logger.warning("[Workflow] No options provided for decision")
            state["enriched_context"]["observation"] = "No options available"
            return

        # Record observation
        state["enriched_context"]["observation"] = {
            "decision_type": decision_type.value,
            "category": decision_type.category.value,
            "task": context.task_description,
            "phase": context.current_phase,
            "component": context.component,
            "option_count": len(options),
            "system_state": context.system_state,
            "risk_tolerance": context.risk_tolerance,
        }

    def _step_gather_context(self, state: Dict[str, Any]) -> None:
        """Step 2: Gather Context - Collect information from all available sources."""
        context: DecisionContext = state["context"]
        config: DecisionManagerConfig = state["config"]

        logger.debug("[Workflow] GATHER_CONTEXT: Collecting from memory, goals, intent")

        enriched = state["enriched_context"]

        # 1. Intent classification (if available and relevant)
        if state["intent_classifier"] and context.user_input:
            try:
                classification = state["intent_classifier"](context.user_input)
                enriched["intent"] = {
                    "type": classification.intent.value,
                    "confidence": classification.confidence,
                    "requires_planning": classification.should_plan,
                    "should_answer_directly": classification.should_answer_directly,
                    "includes_runtime_context": classification.should_include_runtime_context,
                }
            except Exception as e:
                logger.debug(f"[Workflow] Intent classification failed: {e}")

        # 2. Goal context (if available)
        if state["goal_storage"] and config.use_goal_scheduling:
            try:
                active_goal = state["goal_storage"].active_goal()
                if active_goal:
                    enriched["active_goal"] = {
                        "id": active_goal.id,
                        "name": active_goal.name,
                        "description": active_goal.description,
                        "priority": active_goal.priority,
                        "status": active_goal.status,
                    }
                # Get queued goals
                queue = state["goal_storage"].queue()
                if queue:
                    enriched["queued_goals"] = [
                        {"id": g.id, "name": g.name, "priority": g.priority}
                        for g in queue[:5]
                    ]
            except Exception as e:
                logger.debug(f"[Workflow] Goal context gathering failed: {e}")

        # 3. Memory retrieval (if available)
        if state["unified_retrieval"] and config.use_memory_retrieval and context.task_description:
            try:
                query = RetrievalQuery(
                    query=context.task_description,
                    context={"phase": context.current_phase},
                    max_results=10,
                    min_score=0.2,
                )
                results = state["unified_retrieval"].retrieve(query)
                enriched["memory_results"] = [
                    {
                        "source": r.source,
                        "content": r.content[:200],
                        "score": r.score,
                        "metadata": r.metadata,
                    }
                    for r in results
                ]
            except Exception as e:
                logger.debug(f"[Workflow] Memory retrieval failed: {e}")

        # 4. Planner context (if available)
        if state["planner"] and context.plan_id:
            # Could retrieve plan details
            enriched["plan_id"] = context.plan_id

        # 5. Working memory context
        if context.working_memory:
            enriched["working_memory"] = context.working_memory

        # Merge with existing context
        if context.memory_results:
            enriched.setdefault("memory_results", []).extend(context.memory_results)

        logger.debug(f"[Workflow] GATHER_CONTEXT: Enriched with {len(enriched)} context sources")

    def _step_identify_actions(self, state: Dict[str, Any]) -> None:
        """Step 3: Identify Actions - Validate and enhance available options."""
        options: List[DecisionOption] = state["options"]
        context: DecisionContext = state["context"]
        config: DecisionManagerConfig = state["config"]

        logger.debug(f"[Workflow] IDENTIFY_ACTIONS: Processing {len(options)} options")

        # Limit options if too many
        if len(options) > config.max_options_to_evaluate:
            options = options[:config.max_options_to_evaluate]
            logger.warning(f"[Workflow] Limited options to {config.max_options_to_evaluate}")

        # Enhance each option with context-aware estimates
        enriched_options = []
        for opt in options:
            enhanced = self._enhance_option(opt, context, state["enriched_context"])
            enriched_options.append(enhanced)

        state["options"] = enriched_options
        state["enriched_context"]["identified_actions"] = len(enriched_options)

    def _enhance_option(
        self,
        option: DecisionOption,
        context: DecisionContext,
        enriched_context: Dict[str, Any],
    ) -> DecisionOption:
        """Enhance an option with context-aware estimates."""
        # This is a placeholder for more sophisticated enhancement
        # In practice, this could:
        # - Use memory to find historical success rates for similar actions
        # - Use risk analyzer to assess specific risks
        # - Use planner to estimate effort

        # Add related memories if any
        if "memory_results" in enriched_context:
            relevant = [
                r for r in enriched_context["memory_results"]
                if option.name.lower() in r.get("content", "").lower() or
                any(kw in r.get("content", "").lower() for kw in option.name.split("_"))
            ][:3]
            if relevant:
                option.related_memories = [r.get("source", "") for r in relevant]

        # Adjust estimates based on system state
        if context.system_state == "degraded":
            option.estimated_success *= 0.8
            option.risk_level = "high" if option.risk_level == "medium" else option.risk_level
        elif context.system_state == "critical":
            option.estimated_success *= 0.5
            option.risk_level = "critical"

        # Adjust for risk tolerance
        if context.risk_tolerance == "low" and option.risk_level in ("high", "critical"):
            option.estimated_success *= 0.7
        elif context.risk_tolerance == "high" and option.risk_level == "low":
            option.estimated_success = min(1.0, option.estimated_success * 1.1)

        return option

    def _step_evaluate_options(self, state: Dict[str, Any]) -> None:
        """Step 4: Evaluate Options - Score each option with confidence."""
        options: List[DecisionOption] = state["options"]
        confidence_calculator = state["confidence_calculator"]
        config: DecisionManagerConfig = state["config"]

        logger.debug(f"[Workflow] EVALUATE_OPTIONS: Scoring {len(options)} options")

        evaluated = []
        for opt in options:
            # Calculate confidence score for this option
            if confidence_calculator and config.use_confidence_scoring:
                confidence = self._calculate_option_confidence(opt, state["context"], confidence_calculator)
                opt.confidence_score = confidence.value
                opt.confidence_level = confidence.level.value if hasattr(confidence.level, 'value') else str(confidence.level)
            else:
                # Simple heuristic confidence
                opt.confidence_score = (
                    opt.estimated_success * 0.4 +
                    (1.0 - opt.estimated_effort) * 0.2 +
                    opt.estimated_impact * 0.2 +
                    (1.0 if opt.reversible else 0.5) * 0.2
                )
                opt.confidence_level = self._score_to_level(opt.confidence_score)

            # Calculate risk score
            risk_score = self._calculate_option_risk(opt, state["context"])
            opt.risk_score = risk_score
            opt.risk_level = self._score_to_risk_level(risk_score)

            evaluated.append(opt)

        state["evaluated_options"] = evaluated

    def _calculate_option_confidence(
        self,
        option: DecisionOption,
        context: DecisionContext,
        calculator,
    ) -> Any:
        """Calculate confidence score for an option using the confidence system."""
        # Create a ConfidenceModel appropriate for the decision type
        # Use option's decision_type since context doesn't have it
        decision_type = option.decision_type
        if decision_type.category == DecisionCategory.EXECUTION:
            # Map string to ActionType enum
            action_type_str = option.metadata.get("action_type", "tool_execution")
            try:
                action_type = ActionType(action_type_str)
            except ValueError:
                action_type = ActionType.FILE_EDIT
            model = ActionConfidence(
                action_type=action_type,
                action=option.action,
                reversible=option.reversible,
                side_effects=option.opposing_evidence,
                historical_success_rate=option.estimated_success,
                system_state=context.system_state,
            )
        else:
            model = DecisionConfidence(
                decision_type=decision_type,
                decision=option.action,
                alternatives_considered=1,
                complexity=option.estimated_effort,
                impact=option.estimated_impact,
                context_quality=0.7,
                best_practice_alignment=0.7,
            )

        return model.confidence_score

    def _calculate_option_risk(self, option: DecisionOption, context: DecisionContext) -> float:
        """Calculate risk score for an option (0.0-1.0, higher = more risk)."""
        risk = 0.0

        # Base risk from risk_level
        risk_level_scores = {
            "info": 0.1,
            "low": 0.25,
            "medium": 0.5,
            "high": 0.75,
            "critical": 0.95,
        }
        risk += risk_level_scores.get(option.risk_level, 0.5)

        # Irreversible actions are riskier
        if not option.reversible:
            risk += 0.2

        # High effort actions are riskier
        risk += option.estimated_effort * 0.15

        # System state modifier
        state_modifiers = {
            "normal": 0.0,
            "degraded": 0.1,
            "critical": 0.3,
        }
        risk += state_modifiers.get(context.system_state, 0.0)

        # File modifications are riskier
        if option.file_paths:
            risk += min(0.2, len(option.file_paths) * 0.05)

        return min(1.0, risk)

    def _step_estimate_risk_benefit(self, state: Dict[str, Any]) -> None:
        """Step 5: Estimate Risk/Benefit - Combine risk and benefit for each option."""
        evaluated = state["evaluated_options"]
        risk_analyzer = state["risk_analyzer"]
        config: DecisionManagerConfig = state["config"]

        logger.debug(f"[Workflow] ESTIMATE_RISK_BENEFIT: Analyzing {len(evaluated)} options")

        risk_assessments = {}
        benefit_estimates = {}

        for opt in evaluated:
            # Risk assessment
            if risk_analyzer and config.use_risk_assessment:
                # Could do detailed risk analysis here
                pass

            risk_assessments[opt.id] = {
                "risk_level": opt.risk_level,
                "risk_score": opt.risk_score if hasattr(opt, 'risk_score') else 0.5,
                "reversible": opt.reversible,
                "mitigations": self._suggest_mitigations(opt),
            }

            # Benefit estimate (success * impact / effort)
            effort = max(0.1, opt.estimated_effort)
            benefit = (opt.estimated_success * opt.estimated_impact) / effort
            benefit_estimates[opt.id] = {
                "benefit_score": min(1.0, benefit),
                "estimated_success": opt.estimated_success,
                "estimated_impact": opt.estimated_impact,
                "estimated_effort": opt.estimated_effort,
            }

        state["risk_assessments"] = risk_assessments
        state["benefit_estimates"] = benefit_estimates

    def _suggest_mitigations(self, option: DecisionOption) -> List[str]:
        """Suggest risk mitigations for an option."""
        mitigations = []
        if not option.reversible:
            mitigations.append("Create backup before proceeding")
        if option.risk_level in ("high", "critical"):
            mitigations.append("Require human approval")
        if option.file_paths:
            mitigations.append("Verify file changes with diff before applying")
        if option.estimated_effort > 0.7:
            mitigations.append("Break into smaller steps")
        return mitigations

    def _step_choose_best(self, state: Dict[str, Any]) -> None:
        """Step 6: Choose Best - Select the optimal option."""
        evaluated = state["evaluated_options"]
        risk_assessments = state.get("risk_assessments", {})
        benefit_estimates = state.get("benefit_estimates", {})
        config: DecisionManagerConfig = state["config"]
        context: DecisionContext = state["context"]

        logger.debug("[Workflow] CHOOSE_BEST: Selecting best option")

        if not evaluated:
            logger.warning("[Workflow] No options to choose from")
            state["chosen_option"] = None
            return

        # Score each option: confidence * benefit / risk_penalty
        scored = []
        for opt in evaluated:
            confidence = opt.confidence_score
            benefit = benefit_estimates.get(opt.id, {}).get("benefit_score", 0.5)
            risk_penalty = risk_assessments.get(opt.id, {}).get("risk_score", 0.5)

            # Risk-adjusted score
            # High risk reduces effective confidence
            risk_factor = 1.0 - (risk_penalty * 0.5)
            score = confidence * benefit * risk_factor

            scored.append((score, opt))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        chosen = scored[0][1]
        alternatives = [opt for _, opt in scored[1:]]
        rejected = []  # Could include very low-scoring options

        state["chosen_option"] = chosen
        state["alternatives_considered"] = alternatives[:5]  # Top 5 alternatives
        state["rejected_options"] = rejected

        logger.info(f"[Workflow] CHOSEN: {chosen.name} (score={scored[0][0]:.3f})")

    def _build_result(self, state: Dict[str, Any]) -> DecisionResult:
        """Build the final DecisionResult from workflow state."""
        context: DecisionContext = state["context"]
        chosen: Optional[DecisionOption] = state.get("chosen_option")
        alternatives: List[DecisionOption] = state.get("alternatives_considered", [])
        rejected: List[DecisionOption] = state.get("rejected_options", [])
        evaluated: List[DecisionOption] = state.get("evaluated_options", [])

        # Calculate overall confidence
        if chosen:
            confidence = chosen.confidence_score
            confidence_level = chosen.confidence_level
            risk_level = chosen.risk_level
        else:
            confidence = 0.0
            confidence_level = "critical"
            risk_level = "low"

        # Build rationale
        rationale_parts = []
        if chosen:
            rationale_parts.append(f"Selected '{chosen.name}' as the best option")
            if chosen.supporting_evidence:
                rationale_parts.append(f"Supported by: {'; '.join(chosen.supporting_evidence[:2])}")
            if chosen.opposing_evidence:
                rationale_parts.append(f"Considerations: {'; '.join(chosen.opposing_evidence[:2])}")

        # Add risk/benefit rationale
        if chosen and chosen.id in state.get("risk_assessments", {}):
            risk = state["risk_assessments"][chosen.id]
            if risk.get("mitigations"):
                rationale_parts.append(f"Mitigations: {'; '.join(risk['mitigations'])}")

        if chosen and chosen.id in state.get("benefit_estimates", {}):
            benefit = state["benefit_estimates"][chosen.id]
            rationale_parts.append(f"Benefit score: {benefit['benefit_score']:.2f}")

        rationale = " | ".join(rationale_parts) if rationale_parts else "No specific rationale"

        # Key factors
        key_factors = []
        if chosen:
            if chosen.estimated_success > 0.7:
                key_factors.append("High estimated success rate")
            if chosen.reversible:
                key_factors.append("Action is reversible")
            if chosen.risk_level == "low":
                key_factors.append("Low risk")
            if chosen.related_memories:
                key_factors.append(f"Supported by {len(chosen.related_memories)} memory entries")

        # Determine execution guidance
        should_execute = confidence >= 0.3 and risk_level not in ("critical",)
        requires_approval = risk_level in ("high", "critical") or confidence < 0.5
        approval_reason = ""
        if requires_approval:
            reasons = []
            if risk_level in ("high", "critical"):
                reasons.append(f"risk level is {risk_level}")
            if confidence < 0.5:
                reasons.append(f"confidence is low ({confidence:.0%})")
            approval_reason = " | ".join(reasons)

        result = DecisionResult(
            decision_type=chosen.decision_type if chosen else options[0].decision_type,
            category=chosen.category if chosen else options[0].category if options else DecisionCategory.EXECUTION,
            chosen_option=chosen,
            alternatives_considered=alternatives,
            rejected_options=rejected,
            confidence=confidence,
            confidence_level=confidence_level,
            risk_level=risk_level,
            rationale=rationale,
            key_factors=key_factors,
            evidence_summary=f"Evaluated {len(evaluated)} options",
            should_execute=should_execute,
            requires_approval=requires_approval,
            approval_reason=approval_reason,
            next_steps=self._suggest_next_steps(chosen, context) if chosen else [],
            component=context.component,
            metadata={
                "workflow_steps": len(self.steps),
                "total_options": len(evaluated),
                "enriched_context_keys": list(state.get("enriched_context", {}).keys()),
            },
        )

        return result

    def _suggest_next_steps(self, chosen: DecisionOption, context: DecisionContext) -> List[str]:
        """Suggest follow-up steps after this decision."""
        steps = []
        if chosen.tool_name:
            steps.append(f"Execute {chosen.tool_name} with args: {chosen.tool_args}")
        if chosen.file_paths:
            steps.append(f"Modify files: {', '.join(chosen.file_paths[:3])}")
        if context.current_phase == "planning":
            steps.append("Proceed to execution phase")
        elif context.current_phase == "execution":
            steps.append("Verify results and continue to next step")
        if chosen.risk_level in ("high", "critical"):
            steps.append("Obtain human approval before proceeding")
        return steps

    def _score_to_level(self, score: float) -> str:
        if score >= 0.8:
            return "very_high"
        elif score >= 0.6:
            return "high"
        elif score >= 0.4:
            return "medium"
        elif score >= 0.2:
            return "low"
        return "critical"

    def _score_to_risk_level(self, score: float) -> str:
        if score >= 0.8:
            return "critical"
        elif score >= 0.6:
            return "high"
        elif score >= 0.4:
            return "medium"
        elif score >= 0.2:
            return "low"
        return "info"

    def get_workflow_trace(self) -> List[Dict[str, Any]]:
        """Get the trace of executed workflow steps for debugging."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "completed": s.completed,
                "duration_ms": s.duration_ms,
                "timestamp": s.timestamp,
            }
            for s in self._executed_steps
        ]