from dataclasses import dataclass, field


@dataclass
class AgentState:
    goal: str = ""
    plan: list = field(default_factory=list)
    memory: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    current_step: int = 0
    finished: bool = False