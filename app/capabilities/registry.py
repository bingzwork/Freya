"""Capability Registry.

Single registry for callable capabilities that can answer queries directly
without invoking the LLM. This is the M2 component in the Modular Capability System.

Future callable capabilities register here via the extension port.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import re
import threading

from app.core.logger import logger


@dataclass
class Capability:
    """Definition of a callable capability."""
    name: str
    description: str
    handler: Callable[[Dict[str, Any]], "CapabilityResult"]
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
            if intent_type not in self.intent_types:
                return (False, 0.0)

        # Check exact patterns (higher priority than keywords)
        pattern_matched = False
        for pattern in self.patterns:
            try:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    confidence = max(confidence, 0.98)
                    pattern_matched = True
                    break
            except re.error:
                continue

        # Check keywords (only if no pattern matched at higher confidence)
        if not pattern_matched or confidence < 0.95:
            for keyword in self.keywords:
                if keyword in query_lower:
                    keyword_confidence = 0.4 * (1 + len(keyword) / 10)
                    confidence = min(confidence + keyword_confidence, 0.97)

        return (confidence > 0.5, confidence)


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


class CapabilityRegistry:
    """Registry for callable capabilities.

    This is the single source of truth for all capabilities that can be
    invoked directly by the CapabilityRouter. Future capabilities register
    themselves here via the extension port.
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._keyword_index: Dict[str, List[str]] = {}
        self._lock = threading.RLock()

    def register(self, capability: Capability) -> None:
        """Register a new capability.

        Args:
            capability: The Capability to register.
        """
        with self._lock:
            if capability.name in self._capabilities:
                logger.warning(f"[CapabilityRegistry] Capability '{capability.name}' already exists, replacing")

            self._capabilities[capability.name] = capability

            # Update keyword index
            for keyword in capability.keywords:
                keyword_lower = keyword.lower()
                if keyword_lower not in self._keyword_index:
                    self._keyword_index[keyword_lower] = []
                if capability.name not in self._keyword_index[keyword_lower]:
                    self._keyword_index[keyword_lower].append(capability.name)

            logger.debug(f"[CapabilityRegistry] Registered capability: {capability.name}")

    def unregister(self, name: str) -> bool:
        """Unregister a capability.

        Args:
            name: The name of the capability to unregister.

        Returns:
            True if capability was unregistered, False if not found.
        """
        with self._lock:
            if name not in self._capabilities:
                return False

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
            logger.debug(f"[CapabilityRegistry] Unregistered capability: {name}")
            return True

    def get_capability(self, name: str) -> Optional[Capability]:
        """Get a capability by name.

        Args:
            name: The capability name.

        Returns:
            The Capability object, or None if not found.
        """
        with self._lock:
            return self._capabilities.get(name)

    def get_capabilities(self) -> List[str]:
        """Get list of registered capability names.

        Returns:
            List of capability names.
        """
        with self._lock:
            return list(self._capabilities.keys())

    def find_matching(self, query: str, intent_type: Optional[str] = None) -> List[Tuple[str, float]]:
        """Find all capabilities that match a query.

        Args:
            query: The user query.
            intent_type: The classified intent type.

        Returns:
            List of (capability_name, confidence) tuples, sorted by confidence descending.
        """
        with self._lock:
            matches = []

            for name, capability in self._capabilities.items():
                matched, confidence = capability.matches(query, intent_type)
                if matched:
                    matches.append((name, confidence))

            # Sort by confidence (descending)
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches

    def can_handle(self, query: str, intent_type: Optional[str] = None) -> bool:
        """Check if any capability can handle a query.

        Args:
            query: The user query.
            intent_type: The classified intent type.

        Returns:
            True if a capability can handle the query, False otherwise.
        """
        with self._lock:
            return len(self.find_matching(query, intent_type)) > 0

    def get_all(self) -> Dict[str, Capability]:
        """Get all registered capabilities (copy).

        Returns:
            Dictionary of all capabilities.
        """
        with self._lock:
            return dict(self._capabilities)


# Global registry instance
_registry_instance: Optional[CapabilityRegistry] = None
_registry_lock = threading.Lock()


def get_capability_registry() -> CapabilityRegistry:
    """Get the global capability registry instance (singleton)."""
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = CapabilityRegistry()
        return _registry_instance


def reset_capability_registry() -> None:
    """Reset the global capability registry instance (for testing)."""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None
