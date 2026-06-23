"""PrescriptionCorroborationAgent — billed medicines must be corroborated by the
prescription. A *soft* signal: it routes to MANUAL_REVIEW, never excludes line items
or changes the approved amount, and never fires on bills that merely itemise tests or
fees the prescription doesn't list (that is normal — see test_does_not_flag_tests...)."""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.engine import run_claim
from app.policy import Policy


def _run(submission: dict):
    return asyncio.run(run_claim(submission, Policy.from_file(get_settings().policy_path)))


def _claim(prescription_meds: list[str], bill_lines: list[tuple[str, int]]):
    total = sum(a for _, a in bill_lines)
    return {
        "member_id": "EMP001",
        "claim_category": "consultation",
        "claimed_amount": total,
        "documents": [
            {
                "file_id": "rx",
                "actual_type": "PRESCRIPTION",
                "content": {"patient_name": "Rajesh Kumar", "medicines": prescription_meds},
            },
            {
                "file_id": "bill",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "patient_name": "Rajesh Kumar",
                    "line_items": [{"description": d, "amount": a} for d, a in bill_lines],
                    "total": total,
                },
            },
        ],
    }


def test_unprescribed_billed_medicine_routes_to_manual_review():
    # Bill charges Azithromycin 500mg; only Paracetamol was prescribed → flag.
    decision = _run(
        _claim(["Paracetamol 650mg"], [("Consultation Fee", 1000), ("Azithromycin 500mg", 500)])
    )
    assert decision.status == "MANUAL_REVIEW"
    assert any("Azithromycin" in m for m in decision.messages)


def test_prescribed_medicine_is_not_flagged():
    # Billed medicine matches the prescription (token "azithromycin") → clean approval.
    decision = _run(
        _claim(["Azithromycin 500mg"], [("Consultation Fee", 1000), ("Azithromycin 500mg tablet", 500)])
    )
    assert decision.status == "APPROVED"


def test_does_not_flag_tests_or_fees_absent_from_prescription():
    # The eval-safety guarantee (mirrors TC004): a bill may legitimately itemise tests
    # and fees that never appear on the prescription. These are not specific medicines,
    # so they must NOT be flagged — the claim approves.
    decision = _run(
        _claim(
            ["Paracetamol 650mg", "Vitamin C 500mg"],
            [("Consultation Fee", 1000), ("CBC Test", 300), ("Dengue NS1 Test", 200)],
        )
    )
    assert decision.status == "APPROVED"


def test_no_prescription_means_no_corroboration_flag():
    # Dental is the one category needing no prescription (HOSPITAL_BILL only). Bill-only,
    # no prescription → nothing to corroborate, so the agent does not flag.
    submission = {
        "member_id": "EMP001",
        "claim_category": "dental",
        "claimed_amount": 1500,
        "documents": [
            {
                "file_id": "bill",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "patient_name": "Rajesh Kumar",
                    "line_items": [{"description": "Treatment Charges", "amount": 1500}],
                    "total": 1500,
                },
            }
        ],
    }
    decision = _run(submission)
    assert decision.status == "APPROVED"
