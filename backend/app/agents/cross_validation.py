"""CrossValidationAgent — claim-form vs document consistency (a "three-way match").

The member fills in a form (claimed amount, treatment date); the documents carry their
own amounts and dates. These must line up. When they don't, the claim should not be
auto-approved — it goes to MANUAL_REVIEW for a human to reconcile. This is a *soft*
signal: it never changes the approved amount, it only routes the decision.

Two checks (patient-name consistency lives in DocGate, which BLOCKS on a mismatch):
  • Amount — the claimed amount must match the bill total (within 1% for rounding).
  • Date   — any document that carries a date must be within ~30 days of the claimed
             treatment date (a prescription a few days before the bill is normal; a bill
             from a different month/year is not).

Conservative by construction: a check is skipped when the data it needs is absent (no
bill total, no document date), so it never invents a discrepancy. Every internally
consistent claim passes untouched.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.blackboard import Blackboard, Fact, GateGatedAgent
from app.policy import Policy

_AMOUNT_TOLERANCE = Decimal("0.01")  # 1%
_DATE_WINDOW_DAYS = 30


def _d(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


class CrossValidationAgent(GateGatedAgent):
    name = "cross_validation"
    reads = ["semantic"]
    writes = "verdict.consistency"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        claimed = submission.get("claimed_amount")
        treatment_date = _parse_date(submission.get("treatment_date"))

        extractions = [f.value for f in bb.all() if f.key.startswith("extraction.")]

        issues: list[str] = []

        # ── Amount: claimed vs bill total ────────────────────────────────────
        bill_total: Decimal | None = None
        for ext in extractions:
            if (ext.get("doc_type") or "").upper().endswith("BILL"):
                content = ext.get("content") or {}
                if content.get("total") is not None:
                    bill_total = _d(content["total"])
                elif content.get("line_items"):
                    bill_total = sum(
                        (_d(li.get("amount")) for li in content["line_items"]), Decimal(0)
                    )
                break

        if bill_total is not None and claimed is not None:
            claimed_d = _d(claimed)
            spread = abs(claimed_d - bill_total)
            if spread > _AMOUNT_TOLERANCE * max(claimed_d, bill_total):
                issues.append(
                    f"The claimed amount (₹{claimed_d}) does not match the bill total "
                    f"(₹{bill_total})."
                )

        # ── Date: document dates vs claimed treatment date ───────────────────
        if treatment_date is not None:
            for ext in extractions:
                content = ext.get("content") or {}
                doc_date = _parse_date(content.get("date"))
                if doc_date is None:
                    continue
                if abs((doc_date - treatment_date).days) > _DATE_WINDOW_DAYS:
                    issues.append(
                        f"The {ext.get('doc_type') or 'document'} is dated {doc_date}, which "
                        f"does not match the claimed treatment date {treatment_date}."
                    )

        if issues:
            return Fact(
                key=self.writes,
                value={
                    "status": "MANUAL_REVIEW",
                    "reason": "DETAILS_MISMATCH",
                    "message": " ".join(issues),
                    "discrepancies": issues,
                },
                author=self.name,
                confidence=0.9,
            )

        return Fact(
            key=self.writes,
            value={
                "status": "PASS",
                "reason": None,
                "message": "Claim form details are consistent with the documents.",
            },
            author=self.name,
            confidence=1.0,
        )
