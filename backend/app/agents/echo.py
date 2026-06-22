"""A trivial agent that proves the engine runs end-to-end (Part 0).

Reads the submission and echoes it back as a fact. This is scaffolding — it is
replaced by the real intake agents (MemberResolver, IntakeValidator) in Part 1.
"""

from __future__ import annotations

from app.blackboard import Agent, Blackboard, Fact


class EchoAgent(Agent):
    name = "echo"
    reads = ["submission"]
    writes = "echo"

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        return Fact(key=self.writes, value={"echo": submission}, author=self.name, confidence=1.0)
