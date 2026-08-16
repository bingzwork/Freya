"""Map existing Freya EventBus activity into presentation-only avatar states."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.core.events import Event, EventBus

from .controller import AvatarController
from .models import AvatarState, GazeTarget


@dataclass(frozen=True)
class EventMapping:
    pattern: str
    state: AvatarState
    gaze_target: GazeTarget = GazeTarget.USER


# These names are emitted by the existing runtime modules.  Wildcard patterns
# are used only where the existing subsystem owns a family of lifecycle events.
_EVENT_MAPPINGS: tuple[EventMapping, ...] = (
    EventMapping("conversation.question.received", AvatarState.LISTENING, GazeTarget.USER),
    EventMapping("conversation.question.routed", AvatarState.THINKING, GazeTarget.CHAT_PANEL),
    EventMapping("conversation.execution.partial_failure", AvatarState.ERROR, GazeTarget.NOTIFICATION),
    EventMapping("browser.started", AvatarState.BROWSING, GazeTarget.BROWSER_PANEL),
    EventMapping("browser.action", AvatarState.BROWSING, GazeTarget.BROWSER_PANEL),
    EventMapping("browser.navigation", AvatarState.BROWSING, GazeTarget.BROWSER_PANEL),
    EventMapping("browser.observation", AvatarState.READING, GazeTarget.BROWSER_PANEL),
    EventMapping("browser.completed", AvatarState.SUCCESS, GazeTarget.RESULTS_PANEL),
    EventMapping("browser.failed", AvatarState.ERROR, GazeTarget.NOTIFICATION),
    EventMapping("memory.*", AvatarState.MEMORY_RECALL, GazeTarget.RESULTS_PANEL),
    EventMapping("plan.created", AvatarState.THINKING, GazeTarget.CHAT_PANEL),
    EventMapping("plan.registered", AvatarState.THINKING, GazeTarget.CHAT_PANEL),
    EventMapping("progress.snapshot", AvatarState.WORKING, GazeTarget.RESULTS_PANEL),
    EventMapping("progress.task_status_changed", AvatarState.WORKING, GazeTarget.RESULTS_PANEL),
    EventMapping("task.started", AvatarState.WORKING, GazeTarget.RESULTS_PANEL),
    EventMapping("task.completed", AvatarState.SUCCESS, GazeTarget.RESULTS_PANEL),
    EventMapping("task.failed", AvatarState.ERROR, GazeTarget.NOTIFICATION),
    EventMapping("verification.*", AvatarState.RUNNING_TESTS, GazeTarget.RESULTS_PANEL),
    EventMapping("research.*", AvatarState.SEARCHING, GazeTarget.RESULTS_PANEL),
    EventMapping("knowledge_acquisition.*", AvatarState.SEARCHING, GazeTarget.RESULTS_PANEL),
    EventMapping("knowledge_retrieval.*", AvatarState.READING, GazeTarget.RESULTS_PANEL),
    EventMapping("capability.*", AvatarState.WORKING, GazeTarget.RESULTS_PANEL),
    EventMapping("job.started", AvatarState.WAITING, GazeTarget.RESULTS_PANEL),
    EventMapping("job.completed", AvatarState.SUCCESS, GazeTarget.RESULTS_PANEL),
    EventMapping("job.failed", AvatarState.ERROR, GazeTarget.NOTIFICATION),
    EventMapping("warning.*", AvatarState.WARNING, GazeTarget.NOTIFICATION),
    EventMapping("error.*", AvatarState.ERROR, GazeTarget.NOTIFICATION),
)


class AvatarStateMapper:
    """Subscribe to the shared EventBus and update an AvatarController.

    The mapper owns no duplicate runtime state.  It keeps only subscription
    handles so it can be detached cleanly when the UI is hidden or Freya shuts
    down.  Unrecognized events are ignored deliberately.
    """

    def __init__(self, event_bus: EventBus, controller: AvatarController) -> None:
        self.event_bus = event_bus
        self.controller = controller
        self._subscriptions: list[str] = []
        self._started = False

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)

    def start(self) -> None:
        if self._started:
            return
        for mapping in _EVENT_MAPPINGS:
            self._subscriptions.append(self.event_bus.subscribe(mapping.pattern, self._on_event))
        self._subscriptions.append(self.event_bus.subscribe("speech.*", self._on_speech_event))
        self._subscriptions.append(self.event_bus.subscribe("tts.*", self._on_speech_event))
        self._started = True

    def stop(self) -> None:
        for subscription_id in self._subscriptions:
            self.event_bus.unsubscribe(subscription_id)
        self._subscriptions.clear()
        self._started = False

    def _on_speech_event(self, event: Event) -> None:
        name = event.name.lower()
        if any(token in name for token in ("started", "start", "speaking", "audio")):
            self.controller.start_speaking(event_name=event.name)
        elif any(token in name for token in ("completed", "finished", "stopped", "ended", "failed")):
            self.controller.stop_speaking(event_name=event.name)

    def _on_event(self, event: Event) -> None:
        mapping = self._mapping_for(event.name)
        if mapping is None:
            return
        payload = event.data if isinstance(event.data, dict) else {}
        if event.name.endswith("completed") and payload.get("success") is False:
            state = AvatarState.ERROR
        else:
            state = mapping.state
        self.controller.set_state(
            state,
            event_name=event.name,
            metadata={"source": event.source, "correlation_id": event.correlation_id},
        )
        self.controller.set_gaze_target(mapping.gaze_target)

    @staticmethod
    def _mapping_for(event_name: str) -> Optional[EventMapping]:
        import fnmatch

        for mapping in _EVENT_MAPPINGS:
            if fnmatch.fnmatch(event_name, mapping.pattern):
                return mapping
        return None


__all__ = ["AvatarStateMapper", "EventMapping"]
