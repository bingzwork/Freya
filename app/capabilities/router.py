"""Capability Router.

Routes user queries to appropriate capability handlers when the query
can be answered directly without invoking the LLM.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
import re

from app.core.logger import logger


class NoCapabilityError(Exception):
    """Raised when no capability can handle a query."""
    pass


@dataclass
class CapabilityResult:
    """Result from executing a capability."""
    success: bool
    data: Any = None
    message: str = ""
    capability_name: str = ""
    execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "message": self.message,
            "capability": self.capability_name,
            "execution_time": self.execution_time,
        }

    def __repr__(self) -> str:
        return f"CapabilityResult(success={self.success}, capability={self.capability_name})"


@dataclass
class Capability:
    """Definition of a capability that Freya can execute."""
    name: str
    description: str
    handler: Callable[[Dict[str, Any]], CapabilityResult]
    patterns: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    intent_types: List[str] = field(default_factory=list)

    def matches(self, query: str, intent_type: Optional[str] = None) -> Tuple[bool, float]:
        """Check if this capability matches the user query.

        Args:
            query: The user query string.
            intent_type: The classified intent type.

        Returns:
            Tuple of (matches: bool, confidence: float)
        """
        confidence = 0.0
        query_lower = query.lower()

        # Check intent type first (as a filter, not a confidence source)
        if intent_type and self.intent_types:
            normalized_intent_type = getattr(intent_type, "value", intent_type)
            if normalized_intent_type not in self.intent_types:
                return (False, 0.0)
            # Intent type matches - this is a prerequisite, not a confidence boost

        # Check exact patterns (higher priority than keywords)
        pattern_matched = False
        for pattern in self.patterns:
            try:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    confidence = max(confidence, 0.98)
                    pattern_matched = True
                    break  # First matching pattern is enough
            except re.error:
                # Invalid pattern, skip
                continue

        # Check keywords (only if no pattern matched at higher confidence)
        if not pattern_matched or confidence < 0.95:
            for keyword in self.keywords:
                keyword_lower = str(keyword).strip().lower()
                if keyword_lower and re.search(rf"(?<!\w){re.escape(keyword_lower)}(?!\w)", query_lower):
                    # Longer keywords = more specific = higher confidence
                    keyword_confidence = 0.4 * (1 + len(keyword) / 10)
                    confidence = min(confidence + keyword_confidence, 0.97)

        return (confidence > 0.5, confidence)


class CapabilityRouter:
    """Routes user queries to appropriate capability handlers.

    The router maintains a registry of capabilities and their handlers.
    When a query is received, it checks each capability to find the best match.
    If a match is found, the corresponding handler is executed.
    If no match is found, a NoCapabilityError is raised.
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._keyword_index: Dict[str, List[str]] = {}
        self._debug_mode: bool = False

    def enable_debug(self) -> None:
        """Enable debug mode for verbose capability routing output."""
        self._debug_mode = True
        logger.info("[CapabilityRouter] Debug mode enabled")

    def disable_debug(self) -> None:
        """Disable debug mode."""
        self._debug_mode = False
        logger.info("[CapabilityRouter] Debug mode disabled")

    @property
    def debug_mode(self) -> bool:
        """Check if debug mode is enabled."""
        return self._debug_mode

    def register(self, capability: Capability) -> None:
        """Register a new capability.

        Args:
            capability: The Capability to register.
        """
        self._capabilities[capability.name] = capability

        # Update keyword index
        for keyword in capability.keywords:
            keyword_lower = keyword.lower()
            if keyword_lower not in self._keyword_index:
                self._keyword_index[keyword_lower] = []
            self._keyword_index[keyword_lower].append(capability.name)

        logger.debug(f"[CapabilityRouter] Registered capability: {capability.name}")

    def unregister(self, name: str) -> None:
        """Unregister a capability.

        Args:
            name: The name of the capability to unregister.
        """
        if name in self._capabilities:
            capability = self._capabilities[name]

            # Remove from keyword index
            for keyword in capability.keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in self._keyword_index:
                    if name in self._keyword_index[keyword_lower]:
                        self._keyword_index[keyword_lower].remove(name)
                        if not self._keyword_index[keyword_lower]:
                            del self._keyword_index[keyword_lower]

            del self._capabilities[name]
            logger.debug(f"[CapabilityRouter] Unregistered capability: {name}")



    def register_capability(
        self,
        name: str,
        handler,
        description: str,
        patterns = None,
        keywords = None,
        intent_types = None,
    ) -> None:
        """Convenience method to register a capability by parameters.
        
        Args:
            name: Capability name
            handler: Handler function
            description: Capability description
            patterns: Regex patterns for matching
            keywords: Keywords for matching
            intent_types: Intent types this capability handles
        """
        capability = Capability(
            name=name,
            description=description,
            handler=handler,
            patterns=patterns or [],
            keywords=keywords or [],
            intent_types=intent_types or [],
        )
        self.register(capability)

    def get_capabilities(self) -> List[str]:
        """Get list of registered capability names.

        Returns:
            List of capability names.
        """
        return list(self._capabilities.keys())

    def get_capability(self, name: str) -> Optional[Capability]:
        """Get a capability by name.

        Args:
            name: The capability name.

        Returns:
            The Capability object, or None if not found.
        """
        return self._capabilities.get(name)

    def find_matching(self, query: str, intent_type: Optional[str] = None) -> List[Tuple[str, float]]:
        """Find all capabilities that match a query.

        Args:
            query: The user query.
            intent_type: The classified intent type.

        Returns:
            List of (capability_name, confidence) tuples, sorted by confidence.
        """
        matches = []

        for name, capability in self._capabilities.items():
            matched, confidence = capability.matches(query, intent_type)
            if matched:
                matches.append((name, confidence))

        # Sort by confidence (descending)
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches

    def execute_named(self, name: str, query: str = "", **context) -> CapabilityResult:
        """Execute one registered capability without rematching the query.

        ExecutionEngine uses this after safety approval, so an approved action
        cannot be re-routed to a different capability by keyword matching.
        """
        import time

        capability = self._capabilities.get(name)
        if capability is None:
            raise NoCapabilityError(f"No registered capability named: {name}")
        start_time = time.time()
        handler_context = {
            "query": query,
            "capability_name": name,
            **context,
        }
        try:
            result = capability.handler(handler_context)
            result.execution_time = time.time() - start_time
            result.capability_name = name
            return result
        except Exception as error:
            logger.error(f"[CapabilityRouter] Error executing capability {name}: {error}")
            return CapabilityResult(
                success=False,
                message=str(error),
                capability_name=name,
                execution_time=time.time() - start_time,
            )

    def route(self, query: str, intent_type: Optional[str] = None, **context) -> CapabilityResult:
        """Route a query to the appropriate capability handler.

        Args:
            query: The user query string.
            intent_type: The classified intent type (e.g., "system_status").
            **context: Additional context to pass to the capability handler.

        Returns:
            CapabilityResult from executing the matched capability.

        Raises:
            NoCapabilityError: If no capability can handle the query.
        """
        import time

        start_time = time.time()

        # Find matching capabilities
        matches = self.find_matching(query, intent_type)

        if not matches:
            if self._debug_mode:
                logger.info(f"[CapabilityRouter] No capability found for query: '{query}'")
            raise NoCapabilityError(f"No capability can handle: {query[:50]}...")

        # Use the highest-confidence match
        best_name, best_confidence = matches[0]
        capability = self._capabilities[best_name]

        if self._debug_mode:
            logger.info(
                f"[CapabilityRouter] Matched capability: {best_name} "
                f"(confidence: {best_confidence:.2f}) for query: '{query[:50]}...'"
            )

        # Build context with query and additional context
        handler_context = {
            "query": query,
            "intent_type": intent_type,
            "capability_name": best_name,
            **context,
        }

        # Execute the capability
        try:
            result = capability.handler(handler_context)
            result.execution_time = time.time() - start_time
            result.capability_name = best_name

            if self._debug_mode:
                logger.info(
                    f"[CapabilityRouter] Executed {best_name} in {result.execution_time:.3f}s: "
                    f"success={result.success}"
                )

            return result

        except Exception as e:
            logger.error(f"[CapabilityRouter] Error executing capability {best_name}: {e}")
            return CapabilityResult(
                success=False,
                message=str(e),
                capability_name=best_name,
                execution_time=time.time() - start_time,
            )

    def can_handle(self, query: str, intent_type: Optional[str] = None) -> bool:
        """Check if any capability can handle a query.

        Args:
            query: The user query.
            intent_type: The classified intent type.

        Returns:
            True if a capability can handle the query, False otherwise.
        """
        return len(self.find_matching(query, intent_type)) > 0


# Global router instance
router = CapabilityRouter()


def route_query(query: str, intent_type: Optional[str] = None, **context) -> Optional[CapabilityResult]:
    """Convenience function to route a query.

    Args:
        query: The user query.
        intent_type: The classified intent type.
        **context: Additional context.

    Returns:
        CapabilityResult if a capability handled the query, None otherwise.
    """
    try:
        return router.route(query, intent_type, **context)
    except NoCapabilityError:
        return None
