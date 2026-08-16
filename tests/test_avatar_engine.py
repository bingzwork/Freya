from __future__ import annotations

from app.avatar.adapters import NoopAvatarAdapter
from app.avatar.controller import AvatarController
from app.avatar.mapping import AvatarStateMapper
from app.avatar.models import AvatarExpression, AvatarState
from app.avatar.runtime import AvatarRuntime
from app.avatar.transport import AvatarUiBridge
from app.core.events import EventBus


def test_controller_is_model_independent_and_expression_falls_back() -> None:
    adapter = NoopAvatarAdapter(
        available_expressions={AvatarExpression.NEUTRAL, AvatarExpression.HAPPY},
    )
    controller = AvatarController(adapter)

    controller.set_state(AvatarState.EXCITED)

    assert controller.snapshot().state is AvatarState.EXCITED
    assert controller.snapshot().expression is AvatarExpression.HAPPY
    assert adapter.commands[-1][0] == "set_expression"


def test_event_bus_mapping_updates_state_and_unsubscribes_cleanly() -> None:
    bus = EventBus()
    adapter = NoopAvatarAdapter()
    controller = AvatarController(adapter)
    mapper = AvatarStateMapper(bus, controller)
    mapper.start()

    bus.emit("conversation.question.received", {"question": "hello"}, source="ConversationControl")
    assert controller.snapshot().state is AvatarState.LISTENING
    bus.emit("browser.navigation", {"url": "https://example.test"}, source="BrowserCapability")
    assert controller.snapshot().state is AvatarState.BROWSING
    bus.emit("memory.lesson_stored", {"title": "event contracts"}, source="MemoryCoordinator")
    assert controller.snapshot().state is AvatarState.MEMORY_RECALL

    subscriptions = mapper.subscription_count
    mapper.stop()
    assert mapper.subscription_count == 0
    bus.emit("browser.failed", {"error": "offline"}, source="BrowserCapability")
    assert controller.snapshot().state is AvatarState.MEMORY_RECALL
    assert subscriptions > 0


def test_speech_lifecycle_resets_lip_sync() -> None:
    adapter = NoopAvatarAdapter()
    controller = AvatarController(adapter)

    controller.start_speaking(event_name="tts.started")
    controller.update_lip_sync(0.8)
    assert controller.snapshot().speaking is True
    assert controller.snapshot().mouth_open == 0.8

    controller.stop_speaking(event_name="tts.completed")
    assert controller.snapshot().speaking is False
    assert controller.snapshot().mouth_open == 0.0
    assert adapter.mouth_open == 0.0


def test_runtime_starts_with_shared_event_bus_and_disposes() -> None:
    bus = EventBus()
    runtime = AvatarRuntime(bus, adapter=NoopAvatarAdapter())
    snapshots = []
    runtime.subscribe(snapshots.append)
    runtime.start()

    bus.emit("plan.created", {"name": "avatar integration"}, source="PlanManager")
    assert runtime.started is True
    assert runtime.snapshot().state is AvatarState.THINKING
    assert snapshots[-1].state is AvatarState.THINKING

    runtime.stop()
    assert runtime.started is False
    assert runtime.controller.adapter.disposed is True


def test_ui_bridge_streams_runtime_snapshots() -> None:
    bus = EventBus()
    runtime = AvatarRuntime(bus, adapter=NoopAvatarAdapter())
    runtime.start()
    bridge = AvatarUiBridge(runtime)
    client_id = bridge.subscribe()

    initial = bridge.next_event(client_id, timeout=0.1)
    assert initial is not None
    bus.emit("browser.navigation", {"url": "https://example.test"}, source="BrowserCapability")
    update = bridge.next_event(client_id, timeout=0.1)
    assert update is not None
    assert update["state"] == "BROWSING"

    bridge.unsubscribe(client_id)
    bridge.close()
    runtime.stop()


def test_disabled_runtime_does_not_subscribe_or_block_startup() -> None:
    bus = EventBus()
    runtime = AvatarRuntime(bus, enabled=False)
    runtime.start()
    assert runtime.started is False
    assert runtime.mapper.subscription_count == 0


def test_adapter_failure_isolated_from_controller() -> None:
    class BrokenAdapter(NoopAvatarAdapter):
        def set_state(self, state: AvatarState) -> None:
            raise RuntimeError("renderer unavailable")

    controller = AvatarController(BrokenAdapter())
    controller.set_state(AvatarState.WORKING)

    assert controller.snapshot().state is AvatarState.IDLE
    assert controller.last_error is not None
    controller.dispose()
