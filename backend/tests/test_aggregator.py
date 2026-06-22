"""DecisionAggregator — proves the §5 precedence ladder, independent of any agent.

Builds a blackboard by hand (posting the facts agents would post) and checks the
reduction. This locks the spine before Parts 2–6 fill in the agents that feed it.
"""

from __future__ import annotations

from decimal import Decimal

from app.aggregator import DecisionAggregator
from app.blackboard import Blackboard, Fact
from app.config import get_settings
from app.policy import Policy


def _policy() -> Policy:
    return Policy.from_file(get_settings().policy_path)


def _bb(*facts: Fact) -> Blackboard:
    bb = Blackboard()
    for fact in facts:
        bb.post(fact)
    return bb


def _decide(*facts: Fact):
    return DecisionAggregator(_policy()).decide(_bb(*facts))


def test_gate_blocked_beats_everything():
    decision = _decide(
        Fact(key="gate", value={"blocked": True, "issues": ["missing HOSPITAL_BILL"]}, author="gate"),
        Fact(key="verdict.waiting", value={"status": "REJECTED", "reason": "WAITING_PERIOD"}, author="w"),
    )
    assert decision.status == "BLOCKED"
    assert "missing HOSPITAL_BILL" in decision.messages


def test_rejection_reasons_are_ranked_excluded_first():
    decision = _decide(
        Fact(key="gate", value={"blocked": False}, author="gate"),
        Fact(key="verdict.limit", value={"status": "REJECTED", "reason": "PER_CLAIM_EXCEEDED"}, author="l"),
        Fact(key="verdict.exclusion_whole", value={"status": "REJECTED", "reason": "EXCLUDED_CONDITION"}, author="e"),
    )
    assert decision.status == "REJECTED"
    assert decision.rejection_reasons[0] == "EXCLUDED_CONDITION"  # outranks PER_CLAIM
    assert set(decision.rejection_reasons) == {"EXCLUDED_CONDITION", "PER_CLAIM_EXCEEDED"}


def test_reject_beats_manual_review():
    decision = _decide(
        Fact(key="verdict.waiting", value={"status": "REJECTED", "reason": "WAITING_PERIOD"}, author="w"),
        Fact(key="verdict.fraud", value={"status": "MANUAL_REVIEW", "message": "velocity"}, author="f"),
    )
    assert decision.status == "REJECTED"


def test_manual_review_carries_financial_amount():
    decision = _decide(
        Fact(key="verdict.fraud", value={"status": "MANUAL_REVIEW", "message": "same-day x4"}, author="f"),
        Fact(key="financial_breakdown", value={"approved_amount": "4800"}, author="calc"),
    )
    assert decision.status == "MANUAL_REVIEW"
    assert decision.approved_amount == Decimal("4800")


def test_partial_when_some_lines_excluded():
    decision = _decide(
        Fact(key="coverage", value={"whole_claim_excluded": False, "covered_count": 1, "excluded_count": 1, "message": "whitening excluded"}, author="e"),
        Fact(key="financial_breakdown", value={"approved_amount": "8000"}, author="calc"),
    )
    assert decision.status == "PARTIAL"
    assert decision.approved_amount == Decimal("8000")


def test_all_lines_excluded_is_rejected_not_partial():
    decision = _decide(
        Fact(key="coverage", value={"whole_claim_excluded": False, "covered_count": 0, "excluded_count": 2, "message": "all excluded"}, author="e"),
    )
    assert decision.status == "REJECTED"
    assert decision.rejection_reasons == ["EXCLUDED_CONDITION"]


def test_default_is_approved_with_amount():
    decision = _decide(
        Fact(key="verdict.intake", value={"status": "PASS"}, author="intake"),
        Fact(key="financial_breakdown", value={"approved_amount": "1350"}, author="calc"),
    )
    assert decision.status == "APPROVED"
    assert decision.approved_amount == Decimal("1350")
