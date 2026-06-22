"""MemberResolver — resolve the claimant (and dependents) against the policy roster.

Posts a ``member`` fact carrying the member record plus the resolved dependent
records. The dependents matter downstream: the document gate's patient-match check
(Part 2) accepts a document addressed to the member *or any covered dependent*
(PRD §4.3, §8.5).
"""

from __future__ import annotations

from app.blackboard import Agent, Blackboard, Fact
from app.policy import Policy


class MemberResolver(Agent):
    name = "member_resolver"
    reads = ["submission"]
    writes = "member"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        member_id = submission.get("member_id")
        record = self.policy.member(member_id)
        if record is None:
            return Fact(
                key=self.writes,
                value={"found": False, "member_id": member_id},
                author=self.name,
                confidence=1.0,
            )
        dependents = [self.policy.member(dep_id) for dep_id in record.get("dependents", [])]
        return Fact(
            key=self.writes,
            value={
                "found": True,
                "record": record,
                "dependents": [d for d in dependents if d is not None],
            },
            author=self.name,
            confidence=1.0,
        )
