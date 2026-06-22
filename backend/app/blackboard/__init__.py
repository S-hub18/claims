"""The blackboard engine — shared fact store, agent contract, and scheduler.

See ARCHITECTURE.md §7. This package is the core that every agent plugs into.
"""

from .core import Agent, AgentState, Blackboard, Fact, GateGatedAgent
from .scheduler import adjudicate

__all__ = ["Agent", "AgentState", "Blackboard", "Fact", "GateGatedAgent", "adjudicate"]
