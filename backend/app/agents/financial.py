"""The financial pipeline — reconcile, then calculate. Order is load-bearing (TC010).

All arithmetic is exact ``decimal.Decimal`` — no float drift. "LLM proposes,
deterministic code decides": the money math is pure Python, never an LLM.

  FinancialReconciler → ``financial_facts``     Σ(line items) vs bill total + divergence
  FinancialCalculator → ``financial_breakdown``  gross → −network discount → −co-pay → cap

The calculation order is the thing TC010 checks: **network discount BEFORE co-pay**
(Apollo ₹4,500 → −20% = ₹3,600 → −10% = ₹3,240). Both agents are gate-gated.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.blackboard import Blackboard, Fact, GateGatedAgent
from app.policy import Policy

_CENT = Decimal("0.01")
_RUPEE = Decimal("1")


def _d(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _bill_hospital(bb: Blackboard) -> str | None:
    """The hospital name from the bill's extracted content, if any."""
    for fact in bb.all():
        if fact.key.startswith("extraction.") and (fact.value.get("doc_type") or "").upper().endswith(
            "BILL"
        ):
            content = fact.value.get("content") or {}
            if content.get("hospital_name"):
                return content["hospital_name"]
    return None


class FinancialReconciler(GateGatedAgent):
    name = "financial_reconciler"
    reads = ["semantic"]
    writes = "financial_facts"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        semantic = bb.get("semantic").value
        lines = semantic.get("lines", [])
        line_sum = sum((_d(line["amount"]) for line in lines), Decimal(0))
        bill_total = _d(semantic["bill_total"]) if semantic.get("bill_total") is not None else None
        divergence = bill_total is not None and abs(line_sum - bill_total) > _CENT
        return Fact(
            key="financial_facts",
            value={
                "line_sum": str(line_sum),
                "bill_total": (str(bill_total) if bill_total is not None else None),
                "divergence": divergence,
            },
            author=self.name,
            confidence=1.0,
        )


class FinancialCalculator(GateGatedAgent):
    name = "financial_calculator"
    reads = ["coverage", "financial_facts", "submission"]
    writes = "financial_breakdown"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        coverage = bb.get("coverage").value
        facts = bb.get("financial_facts").value
        category = coverage.get("category", "")
        cat = self.policy.category(category)
        is_consultation = category.lower() == "consultation"
        sub_limit = _d(cat.get("sub_limit"))

        # gross = Σ covered (post-exclusion) lines, with the consultation-fee line capped
        # at its per-line sub-limit (PRD §4.8/§4.10 step 5). Fallback: bill total, else
        # claimed amount.
        covered = [line for line in coverage.get("lines", []) if not line.get("excluded")]
        amounts = []
        for line in covered:
            amount = _d(line["amount"])
            if is_consultation and line.get("kind") == "consultation_fee" and amount > sub_limit:
                amount = sub_limit
            amounts.append(amount)

        if amounts:
            gross = sum(amounts, Decimal(0))
        elif facts.get("bill_total") is not None:
            gross = _d(facts["bill_total"])
        else:
            gross = _d(submission.get("claimed_amount"))

        # Step 1: network discount FIRST.
        hospital = submission.get("hospital_name") or _bill_hospital(bb)
        discount_pct = (
            _d(cat.get("network_discount_percent", 0))
            if self.policy.is_network_hospital(hospital)
            else Decimal(0)
        )
        discount_amount = gross * discount_pct / 100
        post_discount = gross - discount_amount

        # Step 2: co-pay on the POST-DISCOUNT amount.
        copay_pct = _d(cat.get("copay_percent", 0))
        copay_amount = post_discount * copay_pct / 100
        approved = post_discount - copay_amount

        # Step 3: whole-claim category cap for non-consultation categories
        # (consultation is capped per-line above; its whole-claim ceiling is the
        # max(per_claim, sub_limit) rule, enforced by PerClaimLimitAgent in Part 4).
        cap_applied = False
        if not is_consultation and approved > sub_limit:
            approved = sub_limit
            cap_applied = True

        approved = approved.quantize(_RUPEE, rounding=ROUND_HALF_UP)
        note = (
            f"Gross ₹{gross.quantize(_RUPEE)}"
            + (
                f" → network discount {discount_pct}% (−₹{discount_amount.quantize(_RUPEE)})"
                if discount_pct
                else " → no network discount"
            )
            + (
                f" → co-pay {copay_pct}% on ₹{post_discount.quantize(_RUPEE)} "
                f"(−₹{copay_amount.quantize(_RUPEE)})"
                if copay_pct
                else " → no co-pay"
            )
            + f" → approved ₹{approved}."
        )

        return Fact(
            key="financial_breakdown",
            value={
                "approved_amount": str(approved),
                "gross": str(gross.quantize(_RUPEE)),
                "network_discount": {
                    "pct": str(discount_pct),
                    "amount": str(discount_amount.quantize(_RUPEE)),
                },
                "copay": {"pct": str(copay_pct), "amount": str(copay_amount.quantize(_RUPEE))},
                "sub_limit_cap_applied": cap_applied,
                "currency": "INR",
                "note": note,
            },
            author=self.name,
            confidence=1.0,
        )
