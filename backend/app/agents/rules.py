"""The definitive-rejection rule agents (PRD §4.5/§4.7/§4.8).

Each posts a ``verdict.*`` fact — ``REJECTED`` (with a ranked reason) or ``PASS``. All
are gate-gated, all read their thresholds from policy (zero hardcoded numbers). The
aggregator ranks the reasons (EXCLUDED > WAITING > PRE_AUTH > PER_CLAIM).

  WaitingPeriodAgent  — treatment within a condition's waiting period (TC005)
  PreAuthAgent        — high-value test needing pre-auth that wasn't obtained (TC007)
  PerClaimLimitAgent  — covered amount over the category-aware per-claim ceiling (TC008)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal

from app.blackboard import Blackboard, Fact, GateGatedAgent
from app.policy import Policy


def _d(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _date(value: str | None):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def _clinical_text(bb: Blackboard) -> str:
    """Diagnosis, treatment, tests, and line descriptions across all extractions."""
    parts: list[str] = []
    for fact in bb.all():
        if not fact.key.startswith("extraction."):
            continue
        content = fact.value.get("content") or {}
        for key in ("diagnosis", "treatment"):
            if content.get(key):
                parts.append(str(content[key]))
        for test in content.get("tests_ordered", []) or []:
            parts.append(str(test))
        for item in content.get("line_items", []) or []:
            parts.append(str(item.get("description", "")))
    return " ".join(parts)


class WaitingPeriodAgent(GateGatedAgent):
    name = "waiting_period"
    reads = ["submission", "member"]
    writes = "verdict.waiting"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        member = bb.get("member").value
        words = _words(_clinical_text(bb))
        conditions = self.policy.get("waiting_periods.specific_conditions", {})

        # A condition matches only when *every* significant token of its policy key
        # appears as a whole word — so "joint_replacement" needs both "joint" AND
        # "replacement" (not "joint pain"), and "hernia" never matches "herniation".
        matched, wait_days = None, None
        for condition, days in conditions.items():
            tokens = [t for t in condition.split("_") if len(t) >= 4]
            if tokens and all(token in words for token in tokens):
                matched, wait_days = condition, days
                break

        if not matched or not member.get("found"):
            return Fact(key=self.writes, value={"status": "PASS"}, author=self.name, confidence=1.0)

        join = _date(member["record"].get("join_date"))
        treated = _date(submission.get("treatment_date"))
        if join is None or treated is None:
            return Fact(key=self.writes, value={"status": "PASS"}, author=self.name, confidence=1.0)

        elapsed = (treated - join).days
        if elapsed < wait_days:
            eligible = join + timedelta(days=wait_days)
            label = matched.replace("_", " ")
            return Fact(
                key=self.writes,
                value={
                    "status": "REJECTED",
                    "reason": "WAITING_PERIOD",
                    "message": (
                        f"Treatment for {label} falls within the {wait_days}-day waiting "
                        f"period (member joined {join.isoformat()}, treated "
                        f"{treated.isoformat()}, {elapsed} days later). The member is "
                        f"eligible for {label} claims from {eligible.isoformat()}."
                    ),
                },
                author=self.name,
                confidence=1.0,
            )
        return Fact(key=self.writes, value={"status": "PASS"}, author=self.name, confidence=1.0)


class PreAuthAgent(GateGatedAgent):
    name = "pre_auth"
    reads = ["submission"]
    writes = "verdict.preauth"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        category = submission.get("claim_category", "")
        cat = self.policy.category(category)
        high_value = cat.get("high_value_tests_requiring_pre_auth", []) or []
        threshold = (
            _d(cat.get("pre_auth_threshold")) if cat.get("pre_auth_threshold") is not None else None
        )
        text = _clinical_text(bb).lower()
        matched = next((test for test in high_value if test.lower() in text), None)
        has_preauth = bool(
            submission.get("pre_authorization")
            or submission.get("pre_auth_number")
            or submission.get("pre_auth")
        )
        amount = _d(submission.get("claimed_amount"))

        if matched and threshold is not None and amount > threshold and not has_preauth:
            return Fact(
                key=self.writes,
                value={
                    "status": "REJECTED",
                    "reason": "PRE_AUTH_MISSING",
                    "message": (
                        f"Pre-authorization is required for {matched} above ₹{threshold} "
                        f"(this claim is ₹{amount}) and was not obtained. Please obtain "
                        f"pre-authorization from the insurer and resubmit the claim with the "
                        f"pre-auth reference number."
                    ),
                },
                author=self.name,
                confidence=1.0,
            )
        return Fact(key=self.writes, value={"status": "PASS"}, author=self.name, confidence=1.0)


class PerClaimLimitAgent(GateGatedAgent):
    name = "per_claim_limit"
    reads = ["coverage"]
    writes = "verdict.perclaim"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        coverage = bb.get("coverage").value
        category = coverage.get("category", "")
        covered = _d(coverage.get("covered_amount"))
        per_claim = _d(self.policy.per_claim_limit())
        sub_limit = _d(self.policy.category(category).get("sub_limit"))

        # Category-aware ceiling (PRD §4.8): per-claim is a HARD reject only when it is
        # the binding cap (≥ the category sub-limit). Otherwise the sub-limit binds and
        # the calculator CAPS instead of rejecting (e.g. dental ₹8,000 ≤ ₹10,000).
        if per_claim >= sub_limit and covered > per_claim:
            return Fact(
                key=self.writes,
                value={
                    "status": "REJECTED",
                    "reason": "PER_CLAIM_EXCEEDED",
                    "message": (
                        f"The covered amount ₹{covered} exceeds the per-claim limit of "
                        f"₹{per_claim}. This claim cannot be approved as submitted."
                    ),
                },
                author=self.name,
                confidence=1.0,
            )
        return Fact(
            key=self.writes,
            value={"status": "PASS", "binding_ceiling": str(max(per_claim, sub_limit))},
            author=self.name,
            confidence=1.0,
        )
