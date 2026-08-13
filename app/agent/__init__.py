"""
Agent package exports.

The production initializer uses ``AgentFacadeImpl`` as the canonical agent
boundary.  ``FreyaAgent`` remains available as a compatibility export, but is
loaded lazily so importing the production facade does not pull in the legacy
agent runtime and its unrelated optional dependencies.
"""

from app.agent.planner_base import PlannerProtocol
from app.brain.state import ConversationState, Message

__all__ = ["FreyaAgent", "ConversationState", "Message", "PlannerProtocol"]


def __getattr__(name):
    if name == "FreyaAgent":
        from app.agent.core_agent import FreyaAgent
        return FreyaAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
