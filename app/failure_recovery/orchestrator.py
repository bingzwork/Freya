"""Recovery Orchestrator - Coordinates the complete failure recovery lifecycle.

This module provides a single coordinator that manages the full recovery pipeline:
Failure Detection → Root Cause Analysis → Recovery Strategy → Recovery Execution
→ Verification → Learning

Integrates with existing systems:
- DecisionManager: For recovery strategy decisions
- RepairLoop: For code repair attempts
- VerificationRunner: For verification
- Memory systems: For recording lessons and experiences
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.failure_recovery.detector import (
    FailureDetector, FailureEvent, FailureType, FailureSeverity, Recoverability
)
from app.failure_recovery.analyzer import RootCauseAnalyzer, RootCause, CauseCategory

logger = logging.getLogger(__name__)


class RecoveryStage(Enum):
    """Stages in the recovery lifecycle."""

    DETECTION = "detection"                 # Failure detected and classified
    ANALYSIS = "analysis"                   # Root cause analysis performed
    STRATEGY = "strategy"                   # Recovery strategy selected
    EXECUTION = "execution"                 # Recovery action executed
    VERIFICATION = "verification"           # Fix verified
    LEARNING = "learning"                   # Lessons recorded
    COMPLETED = "completed"                 # Recovery complete (success)
    FAILED = "failed"                       # Recovery failed (needs human)


class RecoveryStrategy(Enum):
    """Available recovery strategies in progressive escalation order."""

    RETRY_SAME = "retry_same"               # Retry the exact same operation
    RETRY_WITH_FIX = "retry_with_fix"       # Apply fix and retry
    ALTERNATIVE_APPROACH = "alternative"    # Try completely different approach
    REPLAN = "replan"                       # Generate new plan
    REDUCE_SCOPE = "reduce_scope"           # Simplify the task
    ASK_USER = "ask_user"                   # Pause for user guidance
    ABORT = "abort"                         # Give up on this task
    # Specialized strategies (not in main progression)
    PROVIDER_FAILOVER = "provider_failover" # Switch LLM provider
    INSTALL_DEPENDENCY = "install_dependency" # Install missing dependency
    FIX_PERMISSION = "fix_permission"       # Fix permission issue


# Progressive recovery strategy order (escalation path)
PROGRESSIVE_STRATEGIES = [
    RecoveryStrategy.RETRY_SAME,
    RecoveryStrategy.RETRY_WITH_FIX,
    RecoveryStrategy.ALTERNATIVE_APPROACH,
    RecoveryStrategy.REPLAN,
    RecoveryStrategy.REDUCE_SCOPE,
    RecoveryStrategy.ASK_USER,
    RecoveryStrategy.ABORT,
]

# Maximum recovery attempts
MAX_RECOVERY_ATTEMPTS = 5


@dataclass
class RecoveryAction:
    """A specific recovery action to execute."""

    strategy: RecoveryStrategy
    description: str
    confidence: float  # 0.0-1.0
    estimated_effort: float  # 0.0-1.0
    parameters: Dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "description": self.description,
            "confidence": self.confidence,
            "estimated_effort": self.estimated_effort,
            "parameters": self.parameters,
            "requires_approval": self.requires_approval,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
        }


@dataclass
class RecoveryEvent:
    """An event in the recovery lifecycle."""

    event_id: str = field(default_factory=lambda: f"recov_{uuid.uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    stage: RecoveryStage = RecoveryStage.DETECTION
    failure_event_id: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "stage": self.stage.value,
            "failure_event_id": self.failure_event_id,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class RecoveryAttempt:
    """A single recovery attempt within a progressive recovery sequence."""

    attempt_number: int
    failure_event: FailureEvent
    root_causes: List[RootCause]
    strategy_used: RecoveryStrategy
    actions_taken: List[RecoveryAction]
    verification_result: Optional[Any] = None
    success: bool = False
    duration_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    lessons_learned: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "failure_event_id": self.failure_event.event_id,
            "failure_type": self.failure_event.failure_type.value,
            "root_causes": [c.to_dict() for c in self.root_causes],
            "strategy_used": self.strategy_used.value,
            "actions_taken": [a.to_dict() for a in self.actions_taken],
            "verification_result": str(self.verification_result) if self.verification_result else None,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
            "lessons_learned": self.lessons_learned,
        }


@dataclass
class RecoveryResult:
    """Result of a recovery attempt (single or progressive)."""

    success: bool
    strategy_used: RecoveryStrategy
    actions_taken: List[RecoveryAction] = field(default_factory=list)
    verification_result: Optional[Any] = None
    final_failure: Optional[FailureEvent] = None
    lessons_learned: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    # Progressive recovery tracking
    attempts: List[RecoveryAttempt] = field(default_factory=list)
    progressive: bool = False
    exhausted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "strategy_used": self.strategy_used.value,
            "actions_taken": [a.to_dict() for a in self.actions_taken],
            "verification_result": str(self.verification_result) if self.verification_result else None,
            "final_failure": self.final_failure.to_dict() if self.final_failure else None,
            "lessons_learned": self.lessons_learned,
            "duration_seconds": self.duration_seconds,
            "attempts": [a.to_dict() for a in self.attempts],
            "progressive": self.progressive,
            "exhausted": self.exhausted,
        }


# Type aliases for integration hooks
RecoveryExecutor = Callable[[RecoveryAction, FailureEvent, List[RootCause]], Any]
VerificationCallback = Callable[[], Any]
DecisionCallback = Callable[[FailureEvent, List[RootCause]], RecoveryStrategy]


class RecoveryOrchestrator:
    """Coordinates the complete failure recovery lifecycle.

    Pipeline:
    1. DETECTION - FailureDetector classifies failure
    2. ANALYSIS - RootCauseAnalyzer identifies likely causes
    3. STRATEGY - Select recovery strategy (via DecisionManager or heuristics)
    4. EXECUTION - Execute recovery action (repair, retry, replan, etc.)
    5. VERIFICATION - Verify the fix works
    6. LEARNING - Record outcome for future improvements

    Supports both single-shot recovery and progressive recovery with strategy
    escalation: RETRY_SAME → RETRY_WITH_FIX → ALTERNATIVE_APPROACH → REPLAN
    → REDUCE_SCOPE → ASK_USER → ABORT

    Usage:
        orchestrator = RecoveryOrchestrator(
            decision_manager=dm,
            executor=executor,
            verifier=verifier,
            failure_detector=detector,
        )

        # Single recovery attempt
        result = orchestrator.recover(
            failure_event=event,
            root_causes=causes,
            context={"task": "fix bug", "plan_id": "..."}
        )

        # Progressive recovery (auto-escalates through strategies)
        result = orchestrator.recover_progressive(
            failure_event=event,
            root_causes=causes,
            context={"task": "fix bug", "plan_id": "..."}
        )
    """

    def __init__(
        self,
        failure_detector: Optional[FailureDetector] = None,
        root_cause_analyzer: Optional[RootCauseAnalyzer] = None,
        decision_manager: Optional[Any] = None,  # DecisionManager
        repair_executor: Optional[RecoveryExecutor] = None,
        verification_callback: Optional[VerificationCallback] = None,
        decision_callback: Optional[DecisionCallback] = None,
        max_recovery_attempts: int = 3,
        workspace: str = ".",
    ):
        self.failure_detector = failure_detector or FailureDetector()
        self.root_cause_analyzer = root_cause_analyzer or RootCauseAnalyzer()
        self.decision_manager = decision_manager
        self.repair_executor = repair_executor
        self.verification_callback = verification_callback
        self.decision_callback = decision_callback
        self.max_recovery_attempts = min(max_recovery_attempts, MAX_RECOVERY_ATTEMPTS)
        self.workspace = workspace

        # Recovery event log
        self._recovery_events: List[RecoveryEvent] = []
        self._recovery_history: List[RecoveryResult] = []

        # Stage callbacks
        self._stage_callbacks: Dict[RecoveryStage, List[Callable]] = {
            stage: [] for stage in RecoveryStage
        }

        # Statistics
        self._stats = {
            "total_recoveries": 0,
            "successful": 0,
            "failed": 0,
            "by_strategy": {},
            "by_failure_type": {},
        }

        logger.info(f"[RecoveryOrchestrator] Initialized (max_attempts={self.max_recovery_attempts})")

    def register_stage_callback(
        self, stage: RecoveryStage, callback: Callable[[RecoveryEvent], None]
    ) -> None:
        """Register a callback for a specific recovery stage."""
        self._stage_callbacks[stage].append(callback)
        logger.info(f"[RecoveryOrchestrator] Registered callback for stage: {stage.value}")

    def register_repair_executor(self, executor: RecoveryExecutor) -> None:
        """Register custom repair executor."""
        self.repair_executor = executor

    def register_verification(self, verifier: VerificationCallback) -> None:
        """Register verification callback."""
        self.verification_callback = verifier

    def register_decision_maker(self, decision_maker: DecisionCallback) -> None:
        """Register custom decision maker for strategy selection."""
        self.decision_callback = decision_maker

    # =========================================================================
    # Single Recovery Attempt
    # =========================================================================

    def recover(
        self,
        failure_event: FailureEvent,
        root_causes: Optional[List[RootCause]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecoveryResult:
        """Execute a single recovery attempt for a failure.

        Args:
            failure_event: The failure to recover from
            root_causes: Pre-computed root causes (optional, will analyze if not provided)
            context: Additional context (task, plan_id, etc.)

        Returns:
            RecoveryResult with outcome and details
        """
        start_time = datetime.now()
        context = context or {}
        task_description = failure_event.task_description or context.get("task", "")

        logger.info(f"[RecoveryOrchestrator] Starting recovery for {failure_event.event_id}")
        logger.info(f"  Task: {task_description}")
        logger.info(f"  Attempt: {failure_event.attempt_number}/{failure_event.max_attempts}")

        # Stage 1: DETECTION (already done, but emit event)
        self._emit_event(RecoveryStage.DETECTION, failure_event.event_id,
            f"Failure detected: {failure_event.failure_type.value}",
            {"failure_type": failure_event.failure_type.value,
             "severity": failure_event.severity.value,
             "component": failure_event.component})

        # Stage 2: ANALYSIS
        if root_causes is None:
            root_causes = self.root_cause_analyzer.analyze(failure_event)

        self._emit_event(RecoveryStage.ANALYSIS, failure_event.event_id,
            f"Root cause analysis complete: {len(root_causes)} causes found",
            {"causes": [c.to_dict() for c in root_causes]})

        # Stage 3: STRATEGY SELECTION
        strategy = self._select_recovery_strategy(failure_event, root_causes, context)
        self._emit_event(RecoveryStage.STRATEGY, failure_event.event_id,
            f"Recovery strategy selected: {strategy.value}",
            {"strategy": strategy.value, "root_causes": [c.category.value for c in root_causes]})

        # Stage 4: EXECUTION
        actions = self._generate_recovery_actions(strategy, failure_event, root_causes, context)
        execution_results = self._execute_recovery_actions(actions, failure_event, root_causes, context)
        self._emit_event(RecoveryStage.EXECUTION, failure_event.event_id,
            f"Recovery actions executed: {len(actions)} actions",
            {"actions": [a.to_dict() for a in actions], "results": execution_results})

        # Stage 5: VERIFICATION
        verification_result = self._verify_recovery(failure_event, context)
        success = self._check_verification_success(verification_result)
        self._emit_event(RecoveryStage.VERIFICATION, failure_event.event_id,
            f"Verification {'passed' if success else 'failed'}",
            {"success": success, "verified": verification_result is not None})

        # Stage 6: LEARNING
        lessons = self._record_learning(failure_event, root_causes, strategy, success, context)
        self._emit_event(RecoveryStage.LEARNING, failure_event.event_id,
            f"Learning recorded: {len(lessons)} lessons",
            {"lessons": lessons})

        # Final result
        duration = (datetime.now() - start_time).total_seconds()
        final_stage = RecoveryStage.COMPLETED if success else RecoveryStage.FAILED

        # Create attempt record for history filtering
        attempt = RecoveryAttempt(
            attempt_number=failure_event.attempt_number,
            failure_event=failure_event,
            root_causes=root_causes,
            strategy_used=strategy,
            actions_taken=actions,
            verification_result=verification_result,
            success=success,
            duration_seconds=duration,
            lessons_learned=lessons,
        )

        result = RecoveryResult(
            success=success,
            strategy_used=strategy,
            actions_taken=actions,
            verification_result=verification_result,
            final_failure=None if success else failure_event,
            lessons_learned=lessons,
            duration_seconds=duration,
            attempts=[attempt],
        )

        self._recovery_history.append(result)
        self._update_stats(failure_event.failure_type, strategy, success)

        self._emit_event(final_stage, failure_event.event_id,
            f"Recovery {'succeeded' if success else 'failed'} after {duration:.1f}s",
            {"final_result": result.to_dict()})

        logger.info(f"[RecoveryOrchestrator] Recovery {'succeeded' if success else 'FAILED'} "
                    f"(strategy={strategy.value}, duration={duration:.1f}s)")

        return result

    # =========================================================================
    # Progressive Recovery with Strategy Escalation
    # =========================================================================

    def recover_progressive(
        self,
        failure_event: FailureEvent,
        root_causes: Optional[List[RootCause]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RecoveryResult:
        """Execute progressive recovery with strategy escalation.

        Tries strategies in order: RETRY_SAME → RETRY_WITH_FIX → ALTERNATIVE_APPROACH
        → REPLAN → REDUCE_SCOPE → ASK_USER → ABORT
        Stops on first success. Maximum MAX_RECOVERY_ATTEMPTS total attempts.

        Args:
            failure_event: The failure to recover from
            root_causes: Pre-computed root causes (optional)
            context: Additional context (task, plan_id, etc.)

        Returns:
            RecoveryResult with full attempt history
        """
        start_time = datetime.now()
        context = context or {}
        task_description = failure_event.task_description or context.get("task", "")

        logger.info(f"[RecoveryOrchestrator] Starting PROGRESSIVE recovery for {failure_event.event_id}")
        logger.info(f"  Task: {task_description}")
        logger.info(f"  Max attempts: {self.max_recovery_attempts}")

        # Track all attempts for this recovery session
        all_attempts: List[RecoveryAttempt] = []
        previous_strategy: Optional[RecoveryStrategy] = None

        # Get initial root causes
        if root_causes is None:
            root_causes = self.root_cause_analyzer.analyze(failure_event)

        # Determine starting strategy order
        strategy_order = self._get_progressive_strategy_order(failure_event, root_causes)
        strategy_index = 0

        # Progressive recovery loop
        for attempt_num in range(1, self.max_recovery_attempts + 1):
            if strategy_index >= len(strategy_order):
                break

            strategy = strategy_order[strategy_index]

            # Skip if same strategy as previous (unless explicitly justified)
            if previous_strategy == strategy and strategy not in (
                RecoveryStrategy.RETRY_SAME, RecoveryStrategy.RETRY_WITH_FIX
            ):
                strategy_index += 1
                if strategy_index >= len(strategy_order):
                    break
                strategy = strategy_order[strategy_index]

            logger.info(f"[RecoveryOrchestrator] Attempt {attempt_num}/{self.max_recovery_attempts}: "
                        f"Strategy = {strategy.value}")

            # Execute this recovery attempt
            attempt_result = self._execute_single_attempt(
                attempt_number=attempt_num,
                failure_event=failure_event,
                root_causes=root_causes,
                strategy=strategy,
                context=context,
            )

            all_attempts.append(attempt_result)

            if attempt_result.success:
                # SUCCESS - stop progressive recovery
                logger.info(f"[RecoveryOrchestrator] Recovery SUCCEEDED on attempt {attempt_num} "
                            f"with strategy {strategy.value}")

                duration = (datetime.now() - start_time).total_seconds()

                # Compile final result
                final_result = RecoveryResult(
                    success=True,
                    strategy_used=strategy,
                    actions_taken=attempt_result.actions_taken,
                    verification_result=attempt_result.verification_result,
                    final_failure=None,
                    lessons_learned=attempt_result.lessons_learned,
                    duration_seconds=duration,
                    attempts=all_attempts,
                    progressive=True,
                    exhausted=False,
                )

                self._recovery_history.append(final_result)
                self._update_stats(failure_event.failure_type, strategy, True)
                self._emit_event(RecoveryStage.COMPLETED, failure_event.event_id,
                    f"Progressive recovery succeeded after {attempt_num} attempts",
                    {"total_attempts": attempt_num, "final_strategy": strategy.value})

                return final_result

            # Failed - record failure, move to next strategy
            logger.warning(f"[RecoveryOrchestrator] Attempt {attempt_num} failed with {strategy.value}")
            previous_strategy = strategy
            strategy_index += 1

            # Update failure event with new attempt number
            if attempt_num < self.max_recovery_attempts:
                data = failure_event.to_dict()
                data["attempt_number"] = attempt_num + 1
                failure_event = FailureEvent.from_dict(data)
                root_causes = self.root_cause_analyzer.analyze(failure_event)

        # All attempts exhausted
        logger.error(f"[RecoveryOrchestrator] Progressive recovery EXHAUSTED after {len(all_attempts)} attempts")
        duration = (datetime.now() - start_time).total_seconds()

        final_result = RecoveryResult(
            success=False,
            strategy_used=all_attempts[-1].strategy_used if all_attempts else RecoveryStrategy.ABORT,
            actions_taken=all_attempts[-1].actions_taken if all_attempts else [],
            verification_result=all_attempts[-1].verification_result if all_attempts else None,
            final_failure=failure_event,
            lessons_learned=self._compile_exhaustion_lessons(all_attempts),
            duration_seconds=duration,
            attempts=all_attempts,
            progressive=True,
            exhausted=True,
        )

        self._recovery_history.append(final_result)
        self._update_stats(failure_event.failure_type, final_result.strategy_used, False)
        self._emit_event(RecoveryStage.FAILED, failure_event.event_id,
            f"Progressive recovery exhausted after {len(all_attempts)} attempts",
            {"total_attempts": len(all_attempts), "exhausted": True})

        return final_result

    # =========================================================================
    # Strategy Selection
    # =========================================================================

    def _select_recovery_strategy(
        self,
        failure_event: FailureEvent,
        root_causes: List[RootCause],
        context: Dict[str, Any],
    ) -> RecoveryStrategy:
        """Select the best recovery strategy based on failure and causes."""

        # If decision callback provided (e.g., DecisionManager), use it
        if self.decision_callback:
            try:
                return self.decision_callback(failure_event, root_causes)
            except Exception as e:
                logger.warning(f"[RecoveryOrchestrator] Decision callback failed: {e}")

        # If DecisionManager available, use it
        if self.decision_manager:
            try:
                return self._decide_with_decision_manager(failure_event, root_causes, context)
            except Exception as e:
                logger.warning(f"[RecoveryOrchestrator] DecisionManager failed: {e}")

        # Fallback: heuristic strategy selection
        return self._heuristic_strategy_selection(failure_event, root_causes, context)

    def _decide_with_decision_manager(
        self,
        failure_event: FailureEvent,
        root_causes: List[RootCause],
        context: Dict[str, Any],
    ) -> RecoveryStrategy:
        """Use DecisionManager to select recovery strategy."""
        from app.decision.manager import decide_recovery_action, DecisionManager
        from app.decision.models import DecisionContext, DecisionOption, DecisionType, DecisionCategory

        task = failure_event.task_description or context.get("task", "unknown task")
        failure_reason = failure_event.error_message

        # Get decision from DecisionManager
        decision_result = decide_recovery_action(
            manager=self.decision_manager,
            task=task,
            failure_reason=failure_reason,
            attempt_number=failure_event.attempt_number,
            max_attempts=failure_event.max_attempts,
            context={
                "failure_type": failure_event.failure_type.value,
                "severity": failure_event.severity.value,
                "recoverability": failure_event.recoverability.value,
                "root_causes": [c.category.value for c in root_causes],
                **context,
            },
        )

        # Map decision to recovery strategy
        if decision_result.chosen_option:
            action = decision_result.chosen_option.action
            if "retry_same" in action:
                return RecoveryStrategy.RETRY_SAME
            elif "alternative" in action:
                return RecoveryStrategy.ALTERNATIVE_APPROACH
            elif "pause" in action or "ask" in action:
                return RecoveryStrategy.ASK_USER
            elif "abort" in action:
                return RecoveryStrategy.ABORT

        return RecoveryStrategy.RETRY_WITH_FIX

    def _heuristic_strategy_selection(
        self,
        failure_event: FailureEvent,
        root_causes: List[RootCause],
        context: Dict[str, Any],
    ) -> RecoveryStrategy:
        """Heuristic strategy selection based on failure type and causes."""

        attempt = failure_event.attempt_number
        recoverability = failure_event.recoverability
        primary_cause = root_causes[0].category if root_causes else CauseCategory.UNKNOWN

        # Permission issues - need human
        if primary_cause == CauseCategory.PERMISSION:
            return RecoveryStrategy.ASK_USER

        # Dependency issues - install
        if primary_cause == CauseCategory.DEPENDENCY:
            return RecoveryStrategy.INSTALL_DEPENDENCY

        # Provider issues - failover
        if failure_event.failure_type == FailureType.PROVIDER:
            return RecoveryStrategy.PROVIDER_FAILOVER

        # Verification/Syntax - auto-fix
        if primary_cause in (CauseCategory.SYNTAX_ERROR, CauseCategory.VERIFICATION,
                              CauseCategory.IMPORT_ERROR, CauseCategory.TYPE_ERROR):
            if recoverability == Recoverability.AUTO_RECOVERABLE and attempt <= 2:
                return RecoveryStrategy.RETRY_WITH_FIX

        # Test failures - need code fix
        if primary_cause == CauseCategory.ASSERTION_FAILURE:
            return RecoveryStrategy.RETRY_WITH_FIX

        # Timeout - try alternative
        if primary_cause == CauseCategory.TIMEOUT:
            return RecoveryStrategy.ALTERNATIVE_APPROACH

        # Planning issues - replan
        if failure_event.failure_type == FailureType.PLANNING or primary_cause == CauseCategory.PLANNING:
            return RecoveryStrategy.REPLAN

        # Environmental - may retry
        if failure_event.failure_type == FailureType.ENVIRONMENTAL:
            if attempt <= 2:
                return RecoveryStrategy.RETRY_SAME
            return RecoveryStrategy.ALTERNATIVE_APPROACH

        # Default based on recoverability and attempt
        if recoverability == Recoverability.AUTO_RECOVERABLE and attempt <= 2:
            return RecoveryStrategy.RETRY_WITH_FIX
        elif recoverability == Recoverability.MANUAL_RETRY and attempt <= 2:
            return RecoveryStrategy.RETRY_WITH_FIX
        elif recoverability == Recoverability.NEEDS_ALTERNATIVE:
            return RecoveryStrategy.ALTERNATIVE_APPROACH
        elif recoverability == Recoverability.NEEDS_REPLAN:
            return RecoveryStrategy.REPLAN
        elif recoverability == Recoverability.NEEDS_HUMAN:
            return RecoveryStrategy.ASK_USER

        return RecoveryStrategy.ABORT

    def _get_progressive_strategy_order(
        self,
        failure_event: FailureEvent,
        root_causes: List[RootCause],
    ) -> List[RecoveryStrategy]:
        """Determine the progressive strategy order for this failure type."""
        primary_cause = root_causes[0].category if root_causes else CauseCategory.UNKNOWN
        recoverability = failure_event.recoverability

        # Start with contextual strategy based on failure type
        custom_order: List[RecoveryStrategy] = []

        # Specialized strategies for specific failure types (tried first)
        if primary_cause == CauseCategory.DEPENDENCY:
            custom_order.append(RecoveryStrategy.INSTALL_DEPENDENCY)
        elif primary_cause == CauseCategory.PERMISSION:
            custom_order.append(RecoveryStrategy.ASK_USER)
        elif failure_event.failure_type == FailureType.PROVIDER:
            custom_order.append(RecoveryStrategy.PROVIDER_FAILOVER)
        elif primary_cause == CauseCategory.TIMEOUT:
            custom_order.append(RecoveryStrategy.ALTERNATIVE_APPROACH)

        # Then follow standard progressive escalation
        for strategy in PROGRESSIVE_STRATEGIES:
            if strategy not in custom_order:
                custom_order.append(strategy)

        # Filter based on recoverability and attempt number
        attempt = failure_event.attempt_number
        filtered = []
        for s in custom_order:
            if s == RecoveryStrategy.RETRY_SAME and attempt > 1:
                continue  # Don't retry same after first attempt
            if s == RecoveryStrategy.RETRY_WITH_FIX and recoverability == Recoverability.UNRECOVERABLE:
                continue
            if s == RecoveryStrategy.ASK_USER and recoverability != Recoverability.NEEDS_HUMAN:
                # Only ask user if really needed
                pass  # Still include, it's late in the order anyway
            filtered.append(s)

        return filtered

    # =========================================================================
    # Action Generation & Execution
    # =========================================================================

    def _generate_recovery_actions(
        self,
        strategy: RecoveryStrategy,
        failure_event: FailureEvent,
        root_causes: List[RootCause],
        context: Dict[str, Any],
    ) -> List[RecoveryAction]:
        """Generate specific recovery actions for the strategy."""

        actions = []
        primary_cause = root_causes[0] if root_causes else None

        if strategy == RecoveryStrategy.RETRY_SAME:
            actions.append(RecoveryAction(
                strategy=strategy,
                description="Retry the same operation",
                confidence=0.3,
                estimated_effort=0.2,
            ))

        elif strategy == RecoveryStrategy.RETRY_WITH_FIX:
            # Generate fix actions based on root causes
            for cause in root_causes[:2]:
                for fix in cause.suggested_fixes[:2]:
                    actions.append(RecoveryAction(
                        strategy=strategy,
                        description=f"Apply fix: {fix}",
                        confidence=cause.confidence * 0.8,
                        estimated_effort=0.4,
                        parameters={"fix": fix, "cause_category": cause.category.value},
                    ))

        elif strategy == RecoveryStrategy.ALTERNATIVE_APPROACH:
            actions.append(RecoveryAction(
                strategy=strategy,
                description="Try alternative approach/implementation",
                confidence=0.5,
                estimated_effort=0.6,
                parameters={"reason": "Previous approach failed", "causes": [c.category.value for c in root_causes]},
            ))

        elif strategy == RecoveryStrategy.REPLAN:
            actions.append(RecoveryAction(
                strategy=strategy,
                description="Generate new execution plan",
                confidence=0.6,
                estimated_effort=0.5,
                parameters={"original_plan_id": context.get("plan_id")},
            ))

        elif strategy == RecoveryStrategy.INSTALL_DEPENDENCY:
            dep_name = "unknown"
            if primary_cause and primary_cause.evidence:
                for ev in primary_cause.evidence:
                    if "No module named" in ev.excerpt:
                        import re
                        match = re.search(r"No module named '(.+?)'", ev.excerpt)
                        if match:
                            dep_name = match.group(1)
                            break
            actions.append(RecoveryAction(
                strategy=strategy,
                description=f"Install missing dependency: {dep_name}",
                confidence=0.9,
                estimated_effort=0.3,
                parameters={"package": dep_name},
                tool_name="run_terminal",
                tool_args={"command": f"pip install {dep_name}"},
            ))

        elif strategy == RecoveryStrategy.PROVIDER_FAILOVER:
            actions.append(RecoveryAction(
                strategy=strategy,
                description="Switch to alternative LLM provider",
                confidence=0.8,
                estimated_effort=0.2,
                parameters={"current_provider": context.get("provider", "unknown")},
            ))

        elif strategy == RecoveryStrategy.ASK_USER:
            actions.append(RecoveryAction(
                strategy=strategy,
                description="Request user guidance",
                confidence=1.0,
                estimated_effort=0.1,
                requires_approval=True,
            ))

        elif strategy == RecoveryStrategy.ABORT:
            actions.append(RecoveryAction(
                strategy=strategy,
                description="Abort task - maximum recovery attempts exceeded",
                confidence=1.0,
                estimated_effort=0.0,
            ))

        return actions

    def _execute_recovery_actions(
        self,
        actions: List[RecoveryAction],
        failure_event: FailureEvent,
        root_causes: List[RootCause],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Execute recovery actions using registered executor or built-in logic."""

        results = []

        if self.repair_executor:
            # Use custom executor
            for action in actions:
                try:
                    result = self.repair_executor(action, failure_event, root_causes)
                    results.append({"action": action.to_dict(), "result": str(result), "success": True})
                except Exception as e:
                    logger.error(f"[RecoveryOrchestrator] Custom executor failed: {e}")
                    results.append({"action": action.to_dict(), "error": str(e), "success": False})
        else:
            # Use built-in execution logic
            for action in actions:
                result = self._execute_builtin_action(action, failure_event, context)
                results.append(result)

        return results

    def _execute_builtin_action(
        self,
        action: RecoveryAction,
        failure_event: FailureEvent,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a built-in recovery action."""

        if action.strategy == RecoveryStrategy.INSTALL_DEPENDENCY:
            # Actually run pip install
            import subprocess
            package = action.parameters.get("package")
            if package:
                try:
                    result = subprocess.run(
                        ["pip", "install", package],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    return {
                        "action": action.to_dict(),
                        "success": result.returncode == 0,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                except Exception as e:
                    return {"action": action.to_dict(), "success": False, "error": str(e)}

        elif action.strategy == RecoveryStrategy.RETRY_WITH_FIX:
            return {
                "action": action.to_dict(),
                "success": False,
                "note": "Retry with fix requires integration with RepairLoop/patch_engine",
            }

        elif action.strategy == RecoveryStrategy.REPLAN:
            return {
                "action": action.to_dict(),
                "success": False,
                "note": "Replan requires integration with Planner/PlanManager",
            }

        elif action.strategy in (RecoveryStrategy.RETRY_SAME, RecoveryStrategy.ALTERNATIVE_APPROACH):
            return {
                "action": action.to_dict(),
                "success": False,
                "note": f"{action.strategy.value} requires re-execution of task",
            }

        elif action.strategy == RecoveryStrategy.ASK_USER:
            return {
                "action": action.to_dict(),
                "success": False,
                "note": "Waiting for user input",
            }

        elif action.strategy == RecoveryStrategy.ABORT:
            return {
                "action": action.to_dict(),
                "success": True,
                "note": "Task aborted",
            }

        return {"action": action.to_dict(), "success": False, "note": "Unknown action"}

    def _verify_recovery(
        self,
        failure_event: FailureEvent,
        context: Dict[str, Any],
    ) -> Optional[Any]:
        """Run verification after recovery attempt."""

        if self.verification_callback:
            try:
                return self.verification_callback()
            except Exception as e:
                logger.error(f"[RecoveryOrchestrator] Verification callback failed: {e}")
                return None

        # Default: try to run standard verification
        try:
            from app.verification.runner import VerificationRunner
            verifier = VerificationRunner(self.workspace)
            return verifier.dry_run_verify()
        except Exception as e:
            logger.error(f"[RecoveryOrchestrator] Default verification failed: {e}")
            return None

    def _check_verification_success(self, verification_result: Optional[Any]) -> bool:
        """Check if verification passed."""
        if verification_result is None:
            return False
        if hasattr(verification_result, "success"):
            return verification_result.success
        return False

    def _record_learning(
        self,
        failure_event: FailureEvent,
        root_causes: List[RootCause],
        strategy: RecoveryStrategy,
        success: bool,
        context: Dict[str, Any],
    ) -> List[str]:
        """Record lessons learned from recovery attempt."""

        lessons = []

        if success:
            lessons.append(
                f"Strategy {strategy.value} succeeded for {failure_event.failure_type.value} "
                f"failure (causes: {[c.category.value for c in root_causes]})"
            )
        else:
            lessons.append(
                f"Strategy {strategy.value} failed for {failure_event.failure_type.value} - "
                f"consider alternative strategies"
            )

        # Add specific cause lessons
        for cause in root_causes:
            if cause.confidence > 0.7:
                if success:
                    lessons.append(
                        f"Root cause {cause.category.value} effectively addressed by "
                        f"{strategy.value}"
                    )
                else:
                    lessons.append(
                        f"Root cause {cause.category.value} was NOT resolved by "
                        f"{strategy.value} - try {cause.suggested_fixes[0] if cause.suggested_fixes else 'alternative fix'}"
                    )

        return lessons

    def _compile_exhaustion_lessons(self, attempts: List[RecoveryAttempt]) -> List[str]:
        """Compile lessons when all recovery attempts are exhausted."""
        lessons = [
            f"All {len(attempts)} recovery attempts exhausted without success",
        ]
        for attempt in attempts:
            lessons.append(
                f"  Attempt {attempt.attempt_number}: {attempt.strategy_used.value} - "
                f"{'succeeded' if attempt.success else 'failed'}"
            )
        lessons.append("Consider manual intervention or task redesign")
        return lessons

    def _execute_single_attempt(
        self,
        attempt_number: int,
        failure_event: FailureEvent,
        root_causes: List[RootCause],
        strategy: RecoveryStrategy,
        context: Dict[str, Any],
    ) -> RecoveryAttempt:
        """Execute a single recovery attempt with the given strategy."""
        start_time = datetime.now()

        # Update failure event with current attempt number
        data = failure_event.to_dict()
        data["attempt_number"] = attempt_number
        current_failure = FailureEvent.from_dict(data)

        # Emit strategy event
        self._emit_event(RecoveryStage.STRATEGY, failure_event.event_id,
            f"Attempt {attempt_number}: Strategy = {strategy.value}",
            {"attempt": attempt_number, "strategy": strategy.value,
             "root_causes": [c.category.value for c in root_causes]})

        # Generate and execute actions
        actions = self._generate_recovery_actions(strategy, current_failure, root_causes, context)
        execution_results = self._execute_recovery_actions(actions, current_failure, root_causes, context)

        self._emit_event(RecoveryStage.EXECUTION, failure_event.event_id,
            f"Attempt {attempt_number} actions executed: {len(actions)} actions",
            {"actions": [a.to_dict() for a in actions], "results": execution_results})

        # Verify
        verification_result = self._verify_recovery(current_failure, context)
        success = self._check_verification_success(verification_result)

        self._emit_event(RecoveryStage.VERIFICATION, failure_event.event_id,
            f"Attempt {attempt_number} verification {'passed' if success else 'failed'}",
            {"success": success, "attempt": attempt_number})

        # Learn
        lessons = self._record_learning(current_failure, root_causes, strategy, success, context)

        duration = (datetime.now() - start_time).total_seconds()

        return RecoveryAttempt(
            attempt_number=attempt_number,
            failure_event=current_failure,
            root_causes=root_causes,
            strategy_used=strategy,
            actions_taken=actions,
            verification_result=verification_result,
            success=success,
            duration_seconds=duration,
            lessons_learned=lessons,
        )

    # =========================================================================
    # Events & Statistics
    # =========================================================================

    def _emit_event(
        self,
        stage: RecoveryStage,
        failure_event_id: str,
        message: str,
        details: Dict[str, Any],
    ) -> None:
        """Emit a recovery lifecycle event."""
        event = RecoveryEvent(
            stage=stage,
            failure_event_id=failure_event_id,
            message=message,
            details=details,
        )
        self._recovery_events.append(event)

        # Call stage callbacks
        for callback in self._stage_callbacks.get(stage, []):
            try:
                callback(event)
            except Exception as e:
                logger.error(f"[RecoveryOrchestrator] Stage callback error: {e}")

        logger.debug(f"[RecoveryOrchestrator] Event: {stage.value} - {message}")

    def _update_stats(
        self,
        failure_type: FailureType,
        strategy: RecoveryStrategy,
        success: bool,
    ) -> None:
        """Update recovery statistics."""
        self._stats["total_recoveries"] += 1
        if success:
            self._stats["successful"] += 1
        else:
            self._stats["failed"] += 1

        self._stats["by_strategy"][strategy.value] = (
            self._stats["by_strategy"].get(strategy.value, 0) + 1
        )
        self._stats["by_failure_type"][failure_type.value] = (
            self._stats["by_failure_type"].get(failure_type.value, 0) + 1
        )

    # =========================================================================
    # History & Analytics
    # =========================================================================

    def get_recovery_history(
        self,
        limit: int = 50,
        failure_type: Optional[str] = None,
        strategy: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> List[RecoveryResult]:
        """Get recovery attempt history with filters.

        Args:
            limit: Maximum records to return
            failure_type: Filter by failure type (e.g., "compilation", "runtime_error")
            strategy: Filter by recovery strategy
            outcome: Filter by outcome ("success", "failure", "exhausted")
            since: ISO timestamp - records after this time
            until: ISO timestamp - records before this time

        Returns:
            List of matching RecoveryResult objects
        """
        results = self._recovery_history

        if failure_type:
            results = [r for r in results
                       if any(a.failure_event.failure_type.value == failure_type for a in r.attempts)]

        if strategy:
            results = [r for r in results
                       if any(a.strategy_used.value == strategy for a in r.attempts)]

        if outcome:
            if outcome == "success":
                results = [r for r in results if r.success]
            elif outcome == "failure":
                results = [r for r in results if not r.success and not r.exhausted]
            elif outcome == "exhausted":
                results = [r for r in results if r.exhausted]

        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                results = [r for r in results
                           if any(datetime.fromisoformat(a.timestamp.replace("Z", "+00:00")) >= since_dt
                                  for a in r.attempts)]
            except ValueError:
                logger.warning(f"[RecoveryOrchestrator] Invalid 'since' timestamp: {since}")

        if until:
            try:
                until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
                results = [r for r in results
                           if any(datetime.fromisoformat(a.timestamp.replace("Z", "+00:00")) <= until_dt
                                  for a in r.attempts)]
            except ValueError:
                logger.warning(f"[RecoveryOrchestrator] Invalid 'until' timestamp: {until}")

        # Sort by most recent first
        results.sort(key=lambda r: r.attempts[-1].timestamp if r.attempts else "", reverse=True)

        return results[:limit]

    def get_recovery_events(self, failure_event_id: Optional[str] = None) -> List[RecoveryEvent]:
        """Get recovery lifecycle events."""
        if failure_event_id:
            return [e for e in self._recovery_events if e.failure_event_id == failure_event_id]
        return self._recovery_events

    def get_statistics(self) -> Dict[str, Any]:
        """Get recovery statistics."""
        stats = self._stats.copy()
        if stats["total_recoveries"] > 0:
            stats["success_rate"] = stats["successful"] / stats["total_recoveries"]
        else:
            stats["success_rate"] = 0.0
        return stats

    def export_recovery_history(self, filepath: Optional[str] = None) -> str:
        """Export recovery history to JSON.

        Args:
            filepath: Optional path to write JSON file. If None, returns JSON string.

        Returns:
            JSON string if filepath is None, otherwise path written.
        """
        import json
        data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_recoveries": len(self._recovery_history),
            "history": [r.to_dict() for r in self._recovery_history],
        }
        json_str = json.dumps(data, indent=2)
        if filepath:
            with open(filepath, 'w') as f:
                f.write(json_str)
            return filepath
        return json_str

    def query_recovery_history(self, **kwargs) -> List[RecoveryResult]:
        """Alias for get_recovery_history with filters."""
        return self.get_recovery_history(**kwargs)

    def get_recovery_analytics(self) -> Dict[str, Any]:
        """Get recovery analytics summary.

        Returns:
            Dictionary with:
            - success_rate: Overall recovery success rate
            - failures_by_category: Count of failures by failure type
            - strategies_used: Count of each strategy used
            - strategy_success_rates: Success rate per strategy
            - avg_attempts_before_success: Average attempts needed for success
            - most_common_strategies: Most frequently used strategies
            - recent_failures: Recent failures needing attention
        """
        total = len(self._recovery_history)
        if total == 0:
            return {
                "total_recoveries": 0,
                "success_rate": 0.0,
                "failures_by_category": {},
                "strategies_used": {},
                "strategy_success_rates": {},
                "avg_attempts_before_success": 0.0,
                "most_common_strategies": [],
                "recent_failures": [],
            }

        # Count by failure category
        failures_by_category: Dict[str, int] = {}
        strategies_used: Dict[str, int] = {}
        strategy_success: Dict[str, List[bool]] = {}
        successful_recoveries = 0
        total_attempts_for_success = 0

        for record in self._recovery_history:
            # Track failure categories
            for attempt in record.attempts:
                ft = attempt.failure_event.failure_type.value
                failures_by_category[ft] = failures_by_category.get(ft, 0) + 1

            # Track strategies
            final_strategy = record.strategy_used.value
            strategies_used[final_strategy] = strategies_used.get(final_strategy, 0) + 1

            if final_strategy not in strategy_success:
                strategy_success[final_strategy] = []
            strategy_success[final_strategy].append(record.success)

            if record.success:
                successful_recoveries += 1
                total_attempts_for_success += len(record.attempts)

        # Strategy success rates
        strategy_success_rates = {}
        for strategy, outcomes in strategy_success.items():
            strategy_success_rates[strategy] = sum(outcomes) / len(outcomes)

        # Most common strategies
        most_common_strategies = sorted(
            strategies_used.items(), key=lambda x: x[1], reverse=True
        )[:5]

        # Recent failures
        recent_failures = [
            r for r in self._recovery_history[-10:] if not r.success
        ]

        return {
            "total_recoveries": total,
            "success_rate": successful_recoveries / total if total > 0 else 0.0,
            "failures_by_category": failures_by_category,
            "strategies_used": strategies_used,
            "strategy_success_rates": strategy_success_rates,
            "avg_attempts_before_success": (
                total_attempts_for_success / successful_recoveries if successful_recoveries > 0 else 0.0
            ),
            "most_common_strategies": most_common_strategies,
            "recent_failures": [
                {
                    "event_id": r.attempts[0].failure_event.event_id if r.attempts else "unknown",
                    "failure_type": r.attempts[0].failure_event.failure_type.value if r.attempts else "unknown",
                    "strategies_tried": [a.strategy_used.value for a in r.attempts],
                    "exhausted": r.exhausted,
                }
                for r in recent_failures
            ],
        }


# Convenience functions for quick recovery
def recover_from_failure(
    failure_event: FailureEvent,
    root_causes: Optional[List[RootCause]] = None,
    context: Optional[Dict[str, Any]] = None,
    **orchestrator_kwargs,
) -> RecoveryResult:
    """Quick recovery - creates orchestrator, runs recovery, returns result."""
    orchestrator = RecoveryOrchestrator(**orchestrator_kwargs)
    return orchestrator.recover(failure_event, root_causes, context)


def recover_progressive(
    failure_event: FailureEvent,
    root_causes: Optional[List[RootCause]] = None,
    context: Optional[Dict[str, Any]] = None,
    **orchestrator_kwargs,
) -> RecoveryResult:
    """Quick progressive recovery - creates orchestrator, runs progressive recovery."""
    orchestrator = RecoveryOrchestrator(**orchestrator_kwargs)
    return orchestrator.recover_progressive(failure_event, root_causes, context)