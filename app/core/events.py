"""
EventBus - Core communication backbone for Freya.

This module provides a unified event system with:
- Publish/Subscribe pattern
- Event registration and validation
- Event filtering and routing
- Priority handling
- Async support
- Event history and replay
- Loose coupling between subsystems
- Thread-safe operations
"""

import asyncio
import inspect
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union
from uuid import uuid4

from app.core.logger import logger


class EventPriority(Enum):
    """Event priority levels for ordered dispatch."""
    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass
class Event:
    """Represents an event in the system."""
    name: str
    data: Any = None
    source: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: str(uuid4()))
    priority: EventPriority = EventPriority.NORMAL
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches(self, filter_pattern: str) -> bool:
        """Check if event matches a filter pattern (supports wildcards)."""
        import fnmatch
        return fnmatch.fnmatch(self.name, filter_pattern)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_id": self.event_id,
            "name": self.name,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
            "priority": self.priority.name,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class Subscription:
    """Represents an event subscription."""
    event_pattern: str
    callback: Callable[[Event], Any]
    filter_func: Optional[Callable[[Event], bool]] = None
    priority: int = 0  # Higher priority = called first
    async_mode: bool = False
    once: bool = False
    subscription_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    call_count: int = 0

    def matches(self, event: Event) -> bool:
        """Check if subscription matches an event."""
        if not event.matches(self.event_pattern):
            return False
        if self.filter_func and not self.filter_func(event):
            return False
        return True


class EventHistory:
    """Maintains a history of events for replay and debugging."""

    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._events: deque = deque(maxlen=max_size)
        self._lock = threading.RLock()
        self._by_name: Dict[str, List[Event]] = defaultdict(list)
        self._by_source: Dict[str, List[Event]] = defaultdict(list)

    def add(self, event: Event) -> None:
        """Add an event to history."""
        with self._lock:
            self._events.append(event)
            self._by_name[event.name].append(event)
            if event.source:
                self._by_source[event.source].append(event)

    def get_recent(self, count: int = 100) -> List[Event]:
        """Get recent events."""
        with self._lock:
            return list(self._events)[-count:]

    def get_by_name(self, name: str, count: int = 100) -> List[Event]:
        """Get events by name."""
        with self._lock:
            return self._by_name.get(name, [])[-count:]

    def get_by_source(self, source: str, count: int = 100) -> List[Event]:
        """Get events by source."""
        with self._lock:
            return self._by_source.get(source, [])[-count:]

    def get_by_pattern(self, pattern: str, count: int = 100) -> List[Event]:
        """Get events matching a pattern."""
        import fnmatch
        with self._lock:
            matches = [e for e in self._events if fnmatch.fnmatch(e.name, pattern)]
            return matches[-count:]

    def clear(self) -> None:
        """Clear history."""
        with self._lock:
            self._events.clear()
            self._by_name.clear()
            self._by_source.clear()

    def stats(self) -> Dict[str, Any]:
        """Get history statistics."""
        with self._lock:
            return {
                "total_events": len(self._events),
                "unique_names": len(self._by_name),
                "unique_sources": len(self._by_source),
                "max_size": self.max_size,
            }


class EventBus:
    """
    Central event bus for Freya.

    Provides pub/sub communication with:
    - Pattern-based subscriptions (wildcards supported)
    - Event filtering
    - Priority-based dispatch
    - Synchronous and asynchronous delivery
    - Event history and replay
    - Thread-safe operations
    - Subscription lifecycle management
    """

    def __init__(
        self,
        history_size: int = 10000,
        max_async_workers: int = 10,
    ):
        """
        Initialize the event bus.

        Args:
            history_size: Maximum number of events to keep in history
            max_async_workers: Maximum concurrent async event handlers
        """
        self._subscriptions: Dict[str, List[Subscription]] = defaultdict(list)
        self._lock = threading.RLock()
        self._history = EventHistory(max_size=history_size)
        self._running = True
        self._async_semaphore: Optional[asyncio.Semaphore] = None
        self._max_async_workers = max_async_workers

    def subscribe(
        self,
        event_pattern: str,
        callback: Callable[[Event], Any],
        *,
        filter_func: Optional[Callable[[Event], bool]] = None,
        priority: int = 0,
        async_mode: bool = False,
        once: bool = False,
    ) -> str:
        """
        Subscribe to events matching a pattern.

        Args:
            event_pattern: Event name pattern (supports wildcards like 'task.*')
            callback: Function to call when event matches
            filter_func: Optional additional filter function
            priority: Priority for dispatch order (higher = first)
            async_mode: If True, callback is run in background thread
            once: If True, subscription is removed after first match

        Returns:
            Subscription ID for later unsubscription
        """
        subscription = Subscription(
            event_pattern=event_pattern,
            callback=callback,
            filter_func=filter_func,
            priority=priority,
            async_mode=async_mode,
            once=once,
        )

        with self._lock:
            self._subscriptions[event_pattern].append(subscription)
            # Sort by priority (highest first)
            self._subscriptions[event_pattern].sort(key=lambda s: s.priority, reverse=True)

        logger.debug(f"Subscribed to '{event_pattern}' (id={subscription.subscription_id[:8]})")
        return subscription.subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe by subscription ID."""
        with self._lock:
            for pattern, subscriptions in self._subscriptions.items():
                for i, sub in enumerate(subscriptions):
                    if sub.subscription_id == subscription_id:
                        subscriptions.pop(i)
                        logger.debug(f"Unsubscribed {subscription_id[:8]} from '{pattern}'")
                        return True
        return False

    def unsubscribe_pattern(self, event_pattern: str) -> int:
        """Unsubscribe all subscriptions for a pattern."""
        with self._lock:
            count = len(self._subscriptions.get(event_pattern, []))
            if count > 0:
                del self._subscriptions[event_pattern]
                logger.debug(f"Unsubscribed all {count} from '{event_pattern}'")
            return count

    def emit(
        self,
        name: str,
        data: Any = None,
        *,
        source: str = "",
        priority: EventPriority = EventPriority.NORMAL,
        tags: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """
        Emit an event synchronously.

        Args:
            name: Event name
            data: Event payload
            source: Event source identifier
            priority: Event priority
            tags: Optional tags
            metadata: Optional metadata

        Returns:
            The emitted event
        """
        event = Event(
            name=name,
            data=data,
            source=source,
            priority=priority,
            tags=tags or {},
            metadata=metadata or {},
        )

        self._dispatch(event)
        return event

    async def emit_async(
        self,
        name: str,
        data: Any = None,
        *,
        source: str = "",
        priority: EventPriority = EventPriority.NORMAL,
        tags: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """
        Emit an event asynchronously.

        Args:
            name: Event name
            data: Event payload
            source: Event source identifier
            priority: Event priority
            tags: Optional tags
            metadata: Optional metadata

        Returns:
            The emitted event
        """
        event = Event(
            name=name,
            data=data,
            source=source,
            priority=priority,
            tags=tags or {},
            metadata=metadata or {},
        )

        await self._dispatch_async(event)
        return event

    def emit_and_wait(
        self,
        name: str,
        data: Any = None,
        *,
        source: str = "",
        priority: EventPriority = EventPriority.NORMAL,
        timeout: float = 30.0,
    ) -> List[Any]:
        """
        Emit an event and wait for all synchronous handlers to complete.

        Returns:
            List of return values from handlers
        """
        event = Event(
            name=name,
            data=data,
            source=source,
            priority=priority,
        )

        return self._dispatch_and_collect(event, timeout)

    def _dispatch(self, event: Event) -> None:
        """Dispatch event to matching subscriptions."""
        # Record in history
        self._history.add(event)

        # Find matching subscriptions
        matching_subs = self._find_matching_subscriptions(event)

        if not matching_subs:
            logger.debug(f"No subscribers for event '{event.name}'")
            return

        logger.debug(f"Dispatching event '{event.name}' to {len(matching_subs)} subscribers")

        # Dispatch synchronously
        for sub in matching_subs:
            try:
                if sub.async_mode:
                    # Run in background thread
                    self._run_async(sub, event)
                else:
                    # Run synchronously - support both old (data) and new (Event) signatures
                    self._call_handler(sub.callback, event)
                    sub.call_count += 1

                # Remove one-time subscriptions
                if sub.once:
                    self.unsubscribe(sub.subscription_id)

            except Exception as e:
                logger.error(f"Error in event handler for '{event.name}': {e}")

    def _call_handler(self, callback: Callable, event: Event) -> None:
        """Call handler with appropriate arguments based on signature."""
        sig = inspect.signature(callback)
        params = list(sig.parameters.keys())

        # Check if callback expects Event object or just data
        if len(params) == 1:
            # Single parameter - could be Event or data
            param = params[0]
            param_annotation = sig.parameters[param].annotation
            if param_annotation == Event or param_annotation == 'Event':
                callback(event)
            else:
                # Assume it wants data
                callback(event.data)
        elif len(params) >= 2:
            # Multiple parameters - pass event and data
            callback(event, event.data)
        else:
            # No parameters
            callback()

    async def _dispatch_async(self, event: Event) -> None:
        """Dispatch event asynchronously."""
        # Record in history
        self._history.add(event)

        # Find matching subscriptions
        matching_subs = self._find_matching_subscriptions(event)

        if not matching_subs:
            logger.debug(f"No subscribers for event '{event.name}'")
            return

        logger.debug(f"Async dispatching event '{event.name}' to {len(matching_subs)} subscribers")

        # Create async semaphore if needed
        if self._async_semaphore is None:
            self._async_semaphore = asyncio.Semaphore(self._max_async_workers)

        # Dispatch async handlers
        tasks = []
        for sub in matching_subs:
            if sub.async_mode:
                task = asyncio.create_task(self._run_async_async(sub, event))
                tasks.append(task)
            else:
                # Run sync handlers in thread pool
                task = asyncio.create_task(self._run_sync_in_executor(sub, event))
                tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _dispatch_and_collect(self, event: Event, timeout: float) -> List[Any]:
        """Dispatch event and collect results from synchronous handlers."""
        self._history.add(event)

        matching_subs = self._find_matching_subscriptions(event)
        results = []

        for sub in matching_subs:
            if not sub.async_mode:
                try:
                    # Support both old and new signatures
                    sig = inspect.signature(sub.callback)
                    params = list(sig.parameters.keys())

                    if len(params) == 1:
                        param = params[0]
                        param_annotation = sig.parameters[param].annotation
                        if param_annotation == Event or param_annotation == 'Event':
                            result = sub.callback(event)
                        else:
                            result = sub.callback(event.data)
                    elif len(params) >= 2:
                        result = sub.callback(event, event.data)
                    else:
                        result = sub.callback()

                    results.append(result)
                    sub.call_count += 1
                except Exception as e:
                    logger.error(f"Error in event handler for '{event.name}': {e}")
                    results.append(e)

                if sub.once:
                    self.unsubscribe(sub.subscription_id)

        return results

    def _find_matching_subscriptions(self, event: Event) -> List[Subscription]:
        """Find all subscriptions matching an event."""
        matching = []

        with self._lock:
            for pattern, subscriptions in self._subscriptions.items():
                for sub in subscriptions:
                    if sub.matches(event):
                        matching.append(sub)

        # Sort by priority (highest first)
        matching.sort(key=lambda s: s.priority, reverse=True)
        return matching

    def _run_async(self, sub: Subscription, event: Event) -> None:
        """Run handler in background thread."""
        def wrapper():
            try:
                self._call_handler(sub.callback, event)
                sub.call_count += 1
            except Exception as e:
                logger.error(f"Error in async event handler for '{event.name}': {e}")

        threading.Thread(target=wrapper, daemon=True).start()

    async def _run_async_async(self, sub: Subscription, event: Event) -> None:
        """Run async handler with semaphore."""
        async with self._async_semaphore:
            try:
                if asyncio.iscoroutinefunction(sub.callback):
                    await self._call_async_handler(sub.callback, event)
                else:
                    # Run sync function in executor
                    await asyncio.get_event_loop().run_in_executor(None, self._call_handler, sub.callback, event)
                sub.call_count += 1
            except Exception as e:
                logger.error(f"Error in async event handler for '{event.name}': {e}")
            finally:
                if sub.once:
                    self.unsubscribe(sub.subscription_id)

    async def _call_async_handler(self, callback: Callable, event: Event) -> None:
        """Call async handler with appropriate arguments."""
        sig = inspect.signature(callback)
        params = list(sig.parameters.keys())

        if len(params) == 1:
            param = params[0]
            param_annotation = sig.parameters[param].annotation
            if param_annotation == Event or param_annotation == 'Event':
                await callback(event)
            else:
                await callback(event.data)
        elif len(params) >= 2:
            await callback(event, event.data)
        else:
            await callback()

    async def _run_sync_in_executor(self, sub: Subscription, event: Event) -> None:
        """Run sync handler in thread pool."""
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._call_handler, sub.callback, event)
            sub.call_count += 1
        except Exception as e:
            logger.error(f"Error in sync event handler for '{event.name}': {e}")
        finally:
            if sub.once:
                self.unsubscribe(sub.subscription_id)

    # Convenience methods

    def on(self, event_pattern: str, **kwargs) -> Callable:
        """
        Decorator for subscribing to events.

        Usage:
            @event_bus.on("task.*")
            def handle_task(event):
                ...
        """
        def decorator(func: Callable[[Event], Any]) -> Callable[[Event], Any]:
            self.subscribe(event_pattern, func, **kwargs)
            return func
        return decorator

    def once(self, event_pattern: str, **kwargs) -> Callable:
        """Decorator for one-time event subscription."""
        return self.on(event_pattern, once=True, **kwargs)

    # Query methods

    def get_subscriptions(self, pattern: Optional[str] = None) -> Dict[str, int]:
        """Get subscription counts."""
        with self._lock:
            if pattern:
                return {pattern: len(self._subscriptions.get(pattern, []))}
            return {p: len(s) for p, s in self._subscriptions.items()}

    def get_subscription_details(self) -> List[Dict[str, Any]]:
        """Get detailed subscription information."""
        with self._lock:
            details = []
            for pattern, subs in self._subscriptions.items():
                for sub in subs:
                    details.append({
                        "subscription_id": sub.subscription_id,
                        "pattern": pattern,
                        "priority": sub.priority,
                        "async_mode": sub.async_mode,
                        "once": sub.once,
                        "call_count": sub.call_count,
                        "created_at": sub.created_at,
                    })
            return details

    def history(self) -> EventHistory:
        """Get event history."""
        return self._history

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()

    def shutdown(self) -> None:
        """Shutdown the event bus."""
        self._running = False
        with self._lock:
            self._subscriptions.clear()
        logger.info("EventBus shutdown complete")


# Global instance for convenience
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def set_event_bus(bus: EventBus) -> None:
    """Set the global event bus instance."""
    global _event_bus
    _event_bus = bus


# Alias for compatibility
events = get_event_bus()