from app.core.events import EventBus


def test_event_bus_emits_to_subscribers() -> None:
    event_bus = EventBus()
    received = []
    event_bus.subscribe("finished", received.append)

    event_bus.emit("finished", {"status": "ok"})

    assert received == [{"status": "ok"}]
