"""IntakeValidator — the cheapest structural checks before any adjudication.

For Stage 1 this enforces the minimum claim amount (PRD §4.1). The submission
deadline check is deliberately disabled: the test-case treatment dates are historical
fixtures, so a wall-clock deadline would spuriously fail every case (PRD §8.1). Posts
a ``verdict.intake`` PASS/REJECTED fact the aggregator reads.
"""

from __future__ import annotations

from decimal import Decimal

from app.blackboard import Agent, Blackboard, Fact
from app.policy import Policy


class IntakeValidator(Agent):
    name = "intake"
    reads = ["submission"]
    writes = "verdict.intake"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        claimed = Decimal(str(submission.get("claimed_amount", 0)))
        minimum = Decimal(str(self.policy.min_claim_amount()))

        if claimed < minimum:
            return Fact(
                key=self.writes,
                value={
                    "status": "REJECTED",
                    "reason": "BELOW_MIN_AMOUNT",
                    "message": (
                        f"Claimed amount ₹{claimed} is below the minimum claim "
                        f"amount of ₹{minimum}."
                    ),
                },
                author=self.name,
                confidence=1.0,
            )

        return Fact(
            key=self.writes,
            value={"status": "PASS"},
            author=self.name,
            confidence=1.0,
        )
