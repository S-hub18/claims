"""Cross-validation — the claim form must agree with the documents.

  • amount mismatch (claimed vs bill total) → MANUAL_REVIEW (CrossValidationAgent)
  • date mismatch (form date vs document date) → MANUAL_REVIEW
  • different patients across documents → BLOCKED (DocGate)
  • fully consistent → APPROVED

A check is skipped when its data is absent, so a consistent claim is never falsely flagged.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.engine import run_claim
from app.policy import Policy


def _run(submission: dict):
    return asyncio.run(run_claim(submission, Policy.from_file(get_settings().policy_path)))


def _claim(amount, treatment_date, presc_name, bill_name, doc_date, bill_total):
    return {
        "member_id": "EMP001",
        "claim_category": "consultation",
        "claimed_amount": amount,
        "treatment_date": treatment_date,
        "documents": [
            {
                "file_id": "rx",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "patient_name": presc_name,
                    "medicines": ["Paracetamol 650mg"],
                    "date": doc_date,
                },
            },
            {
                "file_id": "bill",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "patient_name": bill_name,
                    "date": doc_date,
                    "line_items": [{"description": "Consultation Fee", "amount": bill_total}],
                    "total": bill_total,
                },
            },
        ],
    }


def test_amount_mismatch_routes_to_manual_review():
    d = _run(_claim(8000, "2024-11-01", "Rajesh Kumar", "Rajesh Kumar", "2024-11-01", 1500))
    assert d.status == "MANUAL_REVIEW"
    assert any("does not match the bill total" in m for m in d.messages)


def test_date_mismatch_routes_to_manual_review():
    d = _run(_claim(1500, "2024-11-01", "Rajesh Kumar", "Rajesh Kumar", "2024-01-01", 1500))
    assert d.status == "MANUAL_REVIEW"
    assert any("does not match the claimed treatment date" in m for m in d.messages)


def test_different_patient_names_are_blocked():
    d = _run(_claim(1500, "2024-11-01", "Rajesh Kumar", "Arjun Mehta", "2024-11-01", 1500))
    assert d.status == "BLOCKED"
    text = " ".join(d.messages)
    assert "Rajesh Kumar" in text and "Arjun Mehta" in text


def test_fully_consistent_claim_is_approved():
    d = _run(_claim(1500, "2024-11-01", "Rajesh Kumar", "Rajesh Kumar", "2024-11-01", 1500))
    assert d.status == "APPROVED"
