"""Financial calculator — the load-bearing order (network discount BEFORE co-pay) and
exact decimal arithmetic. Drives the real engine."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from app.config import get_settings
from app.engine import run_claim
from app.policy import Policy


def _run(submission: dict):
    return asyncio.run(run_claim(submission, Policy.from_file(get_settings().policy_path)))


def _consultation(member_id: str, amount: int, hospital: str | None, patient: str):
    doc_bill = {
        "file_id": "B",
        "actual_type": "HOSPITAL_BILL",
        "content": {
            "patient_name": patient,
            # "Treatment Charges" (not a consultation-fee line) so the per-line
            # consultation sub-limit cap doesn't interfere with the order test.
            "line_items": [{"description": "Treatment Charges", "amount": amount}],
            "total": amount,
        },
    }
    if hospital:
        doc_bill["content"]["hospital_name"] = hospital
    submission = {
        "member_id": member_id,
        "claim_category": "CONSULTATION",
        "claimed_amount": amount,
        "documents": [
            {"file_id": "A", "actual_type": "PRESCRIPTION", "content": {"patient_name": patient}},
            doc_bill,
        ],
    }
    if hospital:
        submission["hospital_name"] = hospital
    return submission


def test_non_network_applies_copay_only():
    # 1500 → no discount → 10% co-pay → 1350.
    decision = _run(_consultation("EMP001", 1500, None, "Rajesh Kumar"))
    assert decision.status == "APPROVED"
    assert decision.approved_amount == Decimal("1350")


def test_network_applies_discount_before_copay():
    # Apollo: 4500 → −20% = 3600 → −10% = 3240. Order matters: copay-first would give 3240
    # too here by luck, so check the breakdown proves discount ran first.
    decision = _run(_consultation("EMP010", 4500, "Apollo Hospitals", "Deepak Shah"))
    assert decision.status == "APPROVED"
    assert decision.approved_amount == Decimal("3240")
    breakdown = next(f for f in decision.trace if f.key == "financial_breakdown").value
    assert breakdown["network_discount"]["amount"] == "900"  # 20% of 4500, on gross
    assert breakdown["copay"]["amount"] == "360"  # 10% of 3600 (post-discount), not of 4500


def test_clean_approval_confidence_clears_085():
    decision = _run(_consultation("EMP001", 1500, None, "Rajesh Kumar"))
    assert decision.confidence is not None and decision.confidence > 0.85
