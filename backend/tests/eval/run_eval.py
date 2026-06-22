"""Offline eval scorecard — runs all 12 cases through the engine, prints a per-case
report, and returns the green count. ``make eval``.

Zero LLM calls: the cases carry document ``content`` inline (PRD §8.4), so the whole
suite runs deterministically offline until the live vision pass lands in Part 7. The
green count only goes up as the slices land; the floor is enforced in test_eval.py.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.decision import Decision
from app.engine import run_claim
from app.policy import Policy
from tests.eval.loader import load_cases


def _conf_threshold(spec: str) -> float:
    """Parse an expected confidence spec like ``"above 0.85"`` → ``0.85``."""
    return float(spec.strip().split()[-1])


# The ``system_must`` items are natural-language requirements. We grade them as concrete
# substrings the user-facing message MUST contain — this is what stops a generic error
# from passing (TC001–003 demand the *specific* types/names; TC011 the degradation note).
# Entries are added as each slice makes the case green. Substring match is case-insensitive.
SYSTEM_MUST_SUBSTRINGS = {
    "TC001": ["HOSPITAL_BILL", "PRESCRIPTION"],
    "TC002": ["PHARMACY_BILL", "re-upload"],
    "TC003": ["Rajesh Kumar", "Arjun Mehta"],
    "TC005": ["2024-11-30"],  # eligibility date stated
    "TC006": ["Root Canal", "Teeth Whitening"],  # itemized approve/reject
    "TC007": ["pre-authorization", "resubmit"],
    "TC008": ["5000", "7500"],  # per-claim limit and claimed amount both stated
    "TC009": ["manual review", "same day"],  # flagged pattern, routed not rejected
    "TC011": ["manual review", "component"],
}


def grade(decision: Decision, case: dict[str, Any]) -> list[str]:
    """Return a list of failure strings comparing decision to expected; empty == green.

    Grades structured fields (status, amount, reasons, confidence) plus the registered
    ``system_must`` message-quality substrings for the case.
    """
    expected = case["expected"]
    fails: list[str] = []

    want_status = "BLOCKED" if expected.get("decision") is None else expected["decision"]
    if decision.status != want_status:
        fails.append(f"status: want {want_status}, got {decision.status}")

    if "approved_amount" in expected:
        want = Decimal(str(expected["approved_amount"]))
        got = decision.approved_amount
        if got is None or Decimal(str(got)) != want:
            fails.append(f"amount: want {want}, got {got}")

    if "rejection_reasons" in expected:
        want_reasons = set(expected["rejection_reasons"])
        got_reasons = set(decision.rejection_reasons)
        if not want_reasons.issubset(got_reasons):
            fails.append(f"reasons: want {sorted(want_reasons)}, got {sorted(got_reasons)}")

    if "confidence_score" in expected:
        threshold = _conf_threshold(expected["confidence_score"])
        if decision.confidence is None or decision.confidence <= threshold:
            fails.append(f"confidence: want >{threshold}, got {decision.confidence}")

    text = " ".join(decision.messages + decision.notes).lower()
    for needle in SYSTEM_MUST_SUBSTRINGS.get(case["case_id"], []):
        if needle.lower() not in text:
            fails.append(f"message must mention {needle!r}")

    return fails


async def _adjudicate(case: dict[str, Any], policy: Policy) -> tuple[list[str], Decision]:
    decision = await run_claim(case["input"], policy)
    return grade(decision, case), decision


def run() -> tuple[int, int]:
    policy = Policy.from_file(get_settings().policy_path)
    cases = load_cases()
    bar = "=" * 76
    print(f"\n{bar}\nEVAL SCORECARD — {len(cases)} cases\n{bar}")

    green = 0
    for case in cases:
        fails, decision = asyncio.run(_adjudicate(case, policy))
        ok = not fails
        green += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {case['case_id']}  {case['case_name']}")
        print(
            f"       got: status={decision.status} amount={decision.approved_amount} "
            f"reasons={decision.rejection_reasons} conf={decision.confidence}"
        )
        for failure in fails:
            print(f"       ✗ {failure}")

    print(f"{bar}\n{green}/{len(cases)} GREEN\n{bar}")
    return green, len(cases)


if __name__ == "__main__":
    run()
