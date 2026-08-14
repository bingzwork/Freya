"""
AgentFacadeImpl - Implementation of AgentFacade.

Thin facade implementation (< 500 lines); zero subsystem instantiation.
"""

import time
from typing import Optional

from app.agent.facade import AgentFacade, AgentStatus
from app.routing.unified_router import UnifiedRouter, RouteResult
from app.execution.engine import ExecutionEngine
from app.conversational_control import ConversationControlHandler
from app.core.chat_activity import FreyaChatActivityProvider
from app.core.priority_llm import PriorityLLMProvider, LLMPriority
from app.memory.coordinator import MemoryCoordinator
from app.verification.answer_verifier import AnswerVerifier
from app.core.logger import logger


class AgentFacadeImpl:
    """
    Implements AgentFacade; delegates to composed components.
    """

    def __init__(
        self,
        router: UnifiedRouter,
        execution: ExecutionEngine,
        control: ConversationControlHandler,
        chat_activity: 'FreyaChatActivityProvider',
        priority_llm: PriorityLLMProvider,
        memory: MemoryCoordinator,
        answer_verifier: Optional[AnswerVerifier] = None,
    ):
        self._router = router
        self._execution = execution
        self._control = control
        self._chat_activity = chat_activity
        self._priority_llm = priority_llm
        self._memory = memory
        self._answer_verifier = answer_verifier
        self._start_time = time.time()

    def chat(self, user_input: str) -> str:
        """Handle a chat message through the canonical control, routing, and memory paths."""
        try:
            route_result = self._control.route_question(user_input)
            if route_result.is_control:
                response = self._handle_control(route_result.control_command)
            elif route_result.is_direct_answer:
                response = self._answer_directly(user_input, route_result)
            elif route_result.is_clarification:
                response = self._ask_clarification(user_input, route_result)
            elif route_result.is_engineering:
                response = self._execute_engineering_task(user_input, route_result)
            else:
                response = self._answer_directly(user_input, route_result)

            self._control.record_question_exchange(user_input, response)
            return response
        finally:
            self._control.finish_question()

    def execute_task(self, task: str, allow_mutations: bool = True) -> str:
        """Execute an engineering task directly (bypasses router)."""
        self._chat_activity.chat_started()
        try:
            return self._execution.execute_plan(task, allow_mutations)
        finally:
            self._chat_activity.chat_ended()

    def get_status(self) -> AgentStatus:
        """Get current agent status."""
        return AgentStatus(
            is_executing=self._execution.is_executing,
            is_paused=self._control.is_paused if hasattr(self._control, 'is_paused') else self._execution.is_paused,
            active_plan_id=self._execution.active_plan_id,
            current_task=self._execution.current_task_title,
            completed_tasks=len(self._execution.completed_tasks),
            total_tasks=len(self._execution.plan_tasks),
            chat_active=self._chat_activity.is_chat_active(),
            uptime_seconds=time.time() - self._start_time,
        )

    def shutdown(self) -> None:
        """Shutdown the agent."""
        logger.info("[AgentFacadeImpl] Shutting down...")
        self._execution.shutdown()
        self._priority_llm.shutdown()
        # Infrastructure shutdown handled by SystemInitializer
        logger.info("[AgentFacadeImpl] Shutdown complete")

    # ------------------------------------------------------------------
    # Private helper methods
    # ------------------------------------------------------------------

    def _handle_control(self, control_command) -> str:
        """Handle a control command."""
        from app.conversational_control import ControlCommand

        if control_command == ControlCommand.STOP:
            result = self._control.handle_stop()
        elif control_command == ControlCommand.CANCEL:
            result = self._control.handle_cancel()
        elif control_command == ControlCommand.PAUSE:
            result = self._control.handle_pause()
        elif control_command == ControlCommand.RESUME:
            result = self._control.handle_resume()
        elif control_command == ControlCommand.UNDO:
            result = self._control.handle_undo()
        elif control_command == ControlCommand.REDO:
            result = self._control.handle_redo()
        elif control_command == ControlCommand.STATUS:
            result = self._control.handle_status()
        else:
            result = {"success": False, "message": "Unknown control command"}

        return result.get("message", "Done.")

    def _answer_directly(self, user_input: str, route_result: RouteResult) -> str:
        """Answer through local knowledge, capability handling, or verified fallback."""
        if route_result.answer is not None:
            return route_result.answer

        if route_result.capability_result is not None and route_result.capability_result.success:
            return route_result.capability_result.message

        if route_result.capability_name:
            cap_result = self._router.execute_capability(route_result.capability_name, user_input)
            if cap_result.success:
                return cap_result.message

        # Canonical fallback path: D2 → V1 → AR/SF1 → RESULT.
        system_prompt = """You are Freya, an expert software engineering assistant.
Answer the user's question directly and concisely. Do not create plans or execute tasks
unless explicitly asked to do so."""
        fallback_context = {
            "route_reason": route_result.reason,
            **(route_result.llm_context or {}),
        }
        outcome = self._priority_llm.ask_outcome(
            prompt=route_result.llm_prompt or user_input,
            system=system_prompt,
            priority=route_result.llm_priority or LLMPriority.CHAT,
        )
        if self._answer_verifier is None:
            return "I couldn't generate a reliable answer for that. Answer verification is not configured."
        if not outcome.is_success:
            return self._answer_verifier.handle_provider_failure(
                prompt=user_input,
                context=fallback_context,
                reason=f"{outcome.kind.value}: {outcome.reason}",
            ) or (
                "I couldn't generate a reliable answer for that. The local model "
                "provider did not return a verified response."
            )

        verified = self._answer_verifier.verify_fallback_answer(
            answer=outcome.content or "",
            prompt=user_input,
            context=fallback_context,
        )
        if verified is not None:
            return verified

        # AnswerSafeFailure: never return an unverified draft.
        return "I couldn't generate a reliable answer for that. My internal knowledge doesn't contain sufficient detail, and the local model fallback couldn't produce a verified response."

    def _ask_clarification(self, user_input: str, route_result: RouteResult) -> str:
        """Ask for clarification when intent is ambiguous."""
        from app.intent.entity_extractor import get_missing_slots_prompt
        from app.intent import classify_intent

        classification = classify_intent(user_input)
        return get_missing_slots_prompt(classification.intent, classification.entities)

    def _execute_engineering_task(self, user_input: str, route_result: RouteResult) -> str:
        """Execute an engineering task via the execution engine."""
        return self._execution.execute_plan(user_input)
