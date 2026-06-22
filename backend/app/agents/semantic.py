"""SemanticMapper — map extracted bill content to category-aware, classified line items.

Gate-gated (never runs on a BLOCKED claim). It normalises the hospital bill into a list
of lines, tags the consultation-fee line (which has its own per-line sub-limit, PRD
§4.8/§4.10), and records whether the claim category is covered. Line-item *exclusions*
(cosmetic dental, etc.) are layered on by the ExclusionAgent in Parts 4–5; here every
line starts ``excluded=False``.
"""

from __future__ import annotations

from app.blackboard import Blackboard, Fact, GateGatedAgent
from app.policy import Policy


def _is_bill(doc_type: str | None) -> bool:
    return (doc_type or "").upper().endswith("BILL")


class SemanticMapper(GateGatedAgent):
    name = "semantic_mapper"
    reads = ["submission"]
    writes = "semantic"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        category = submission.get("claim_category", "")
        extractions = [f.value for f in bb.all() if f.key.startswith("extraction.")]
        bill = next((e for e in extractions if _is_bill(e.get("doc_type"))), None)
        content = (bill or {}).get("content") or {}

        lines = []
        for item in content.get("line_items", []) or []:
            desc = item.get("description", "")
            lines.append(
                {
                    "description": desc,
                    "amount": item.get("amount", 0),
                    "kind": "consultation_fee" if "consultation" in desc.lower() else "line",
                    "excluded": False,
                    "reason": None,
                }
            )

        return Fact(
            key="semantic",
            value={
                "category": category,
                "category_covered": self.policy.category(category).get("covered", True),
                "lines": lines,
                "bill_total": content.get("total"),
            },
            author=self.name,
            confidence=1.0,
        )
