"""
LLM Stack - Unified Local LLM Fallback Component.

This component implements the "LLM Stack" from the target architecture (Section 7).
It wraps PriorityLLMProvider and ChatActivityProvider into a single cohesive
interface that serves as a LOCAL LLM FALLBACK ONLY - not the primary knowledge path.

Architecture (from TARGET_ARCHITECTURE.md Section 7):
    LLM Stack
    |-- PriorityLLMProvider -> Ollama / Local Model
    |-- ChatActivityProvider

The LLM Stack exposes a fallback API but must NOT become the primary knowledge path.
Knowledge-first routing (UnifiedRouter -> KnowledgeFirstResolver) must be attempted first.
"""

from typing import Optional
from threading import Lock

from app.core.llm import LLM, ENHANCED_SYSTEM_PROMPT
from app.core.priority_llm import PriorityLLMProvider, LLMPriority, get_priority_llm, set_priority_llm
from app.core.chat_activity import FreyaChatActivityProvider
from app.core.protocols import ChatActivityProvider
from app.core.logger import logger


class LLMStack:
    """
    Unified LLM Stack - Local LLM Fallback Only.

    This component combines:
    - PriorityLLMProvider: Priority-based request queue (CHAT > SAFETY > AUTONOMY > BACKGROUND)
    - ChatActivityProvider: Coordinates chat activity across subsystems

    The LLM Stack is a FALLBACK component. It should only be invoked when:
    1. Knowledge-first routing (UnifiedRouter -> Memory/Experience) returns no answer
    2. No local capability can handle the request
    3. Verification of a generated answer is needed

    It must NOT be used as the primary knowledge path.
    """

    def __init__(
        self,
        model: str = "qwen3.5:4b",
        base_llm: Optional[LLM] = None,
        priority_llm: Optional[PriorityLLMProvider] = None,
        chat_activity: Optional[FreyaChatActivityProvider] = None,
    ):
        """
        Initialize the LLM Stack.

        Args:
            model: Ollama model name (used if base_llm not provided)
            base_llm: Optional pre-configured LLM instance
            priority_llm: Optional pre-configured PriorityLLMProvider
            chat_activity: Optional pre-configured FreyaChatActivityProvider
        """
        # Create base LLM if not provided
        if base_llm is None:
            base_llm = LLM(model=model)

        # Create PriorityLLMProvider if not provided
        if priority_llm is None:
            priority_llm = PriorityLLMProvider(base_llm)
            # Ensure global getter returns this instance
            set_priority_llm(priority_llm)

        # Create ChatActivityProvider if not provided
        if chat_activity is None:
            chat_activity = FreyaChatActivityProvider(priority_llm)

        self._base_llm = base_llm
        self._priority_llm = priority_llm
        self._chat_activity = chat_activity

        logger.info(f"[LLMStack] Initialized with model={model}, provider=Ollama (local fallback)")

    @property
    def priority_llm(self) -> PriorityLLMProvider:
        """Access the underlying PriorityLLMProvider."""
        return self._priority_llm

    @property
    def chat_activity(self) -> FreyaChatActivityProvider:
        """Access the underlying ChatActivityProvider."""
        return self._chat_activity

    @property
    def model(self) -> str:
        """Get the model name."""
        return self._base_llm.model

    # =====================================================================
    # Fallback API - For use when knowledge-first routing fails
    # =====================================================================

    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        priority: LLMPriority = LLMPriority.BACKGROUND,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Synchronous LLM fallback request.

        Use this ONLY when:
        - Knowledge-first routing (UnifiedRouter -> Memory/Experience) returns no answer
        - No local capability can handle the request
        - You need to generate a fallback response

        Args:
            prompt: The user prompt/query
            system: Optional system prompt (defaults to ENHANCED_SYSTEM_PROMPT)
            priority: Request priority (CHAT, SAFETY, AUTONOMY_THINK, BACKGROUND)
            timeout: Optional timeout in seconds

        Returns:
            LLM response string
        """
        return self._priority_llm.ask(
            prompt=prompt,
            system=system or ENHANCED_SYSTEM_PROMPT,
            priority=priority,
            timeout=timeout,
        )

    async def ask_async(
        self,
        prompt: str,
        system: Optional[str] = None,
        priority: LLMPriority = LLMPriority.BACKGROUND,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Asynchronous LLM fallback request.

        Use this ONLY when knowledge-first routing fails.
        """
        return await self._priority_llm.ask_async(
            prompt=prompt,
            system=system or ENHANCED_SYSTEM_PROMPT,
            priority=priority,
            timeout=timeout,
        )

    # =====================================================================
    # Chat Activity Delegation
    # =====================================================================

    def chat_started(self) -> None:
        """Signal chat activity started - autonomy should yield."""
        self._chat_activity.chat_started()

    def chat_ended(self) -> None:
        """Signal chat activity ended - autonomy may resume."""
        self._chat_activity.chat_ended()

    def chat_activity_heartbeat(self) -> None:
        """Record chat activity heartbeat."""
        self._chat_activity.chat_activity()

    def is_chat_active(self) -> bool:
        """Check if chat is currently active."""
        return self._chat_activity.is_chat_active()

    def wait_for_chat_idle(self, timeout: float = 0.1) -> bool:
        """Wait for chat to become idle."""
        return self._chat_activity.wait_for_chat_idle(timeout)

    def register_chat_ended_callback(self, callback) -> None:
        """Register a callback for when chat ends."""
        self._chat_activity.register_chat_ended_callback(callback)

    def unregister_chat_ended_callback(self, callback) -> None:
        """Unregister a chat ended callback."""
        self._chat_activity.unregister_chat_ended_callback(callback)

    # =====================================================================
    # Statistics and Monitoring
    # =====================================================================

    def get_stats(self) -> dict:
        """Get combined statistics from priority LLM and chat activity."""
        stats = self._priority_llm.get_stats()
        stats['model'] = self.model
        stats['chat_active'] = self.is_chat_active()
        return stats

    def shutdown(self) -> None:
        """Shutdown the LLM Stack."""
        logger.info("[LLMStack] Shutting down...")
        self._priority_llm.shutdown()
        logger.info("[LLMStack] Shutdown complete")


# Global LLM Stack instance
_llm_stack: Optional[LLMStack] = None
_llm_stack_lock = Lock()


def get_llm_stack(
    model: str = "qwen3.5:4b",
    base_llm: Optional[LLM] = None,
    priority_llm: Optional[PriorityLLMProvider] = None,
    chat_activity: Optional[FreyaChatActivityProvider] = None,
) -> LLMStack:
    """Get or create the global LLM Stack instance."""
    global _llm_stack
    with _llm_stack_lock:
        if _llm_stack is None:
            _llm_stack = LLMStack(
                model=model,
                base_llm=base_llm,
                priority_llm=priority_llm,
                chat_activity=chat_activity,
            )
        return _llm_stack


def set_llm_stack(stack: LLMStack) -> None:
    """Set the global LLM Stack instance."""
    global _llm_stack
    with _llm_stack_lock:
        _llm_stack = stack