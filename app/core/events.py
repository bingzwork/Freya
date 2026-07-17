from typing import Callable, Dict, List


class EventBus:

    def __init__(self):

        self.events: Dict[str, List[Callable]] = {}


    def subscribe(
        self,
        event_name,
        callback,
    ):

        if event_name not in self.events:

            self.events[event_name] = []

        self.events[event_name].append(
            callback
        )


    def emit(
        self,
        event_name,
        data=None,
    ):

        if event_name not in self.events:

            return

        for callback in self.events[event_name]:

            callback(data)


    def clear(self):

        self.events.clear()



events = EventBus()