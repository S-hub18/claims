"""DocGate — the collect-all gate's three checks and its dependency rule, in isolation
from the eval. Drives the real engine (async via asyncio.run, no plugin)."""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.engine import run_claim
from app.policy import Policy


def _policy() -> Policy:
    return Policy.from_file(get_settings().policy_path)


def _run(submission: dict) -> object:
    return asyncio.run(run_claim(submission, _policy()))


def test_missing_required_document_blocks_and_names_both_types():
    decision = _run(
        {
            "member_id": "EMP001",
            "claim_category": "CONSULTATION",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "A", "actual_type": "PRESCRIPTION"},
                {"file_id": "B", "actual_type": "PRESCRIPTION"},
            ],
        }
    )
    assert decision.status == "BLOCKED"
    text = " ".join(decision.messages)
    assert "HOSPITAL_BILL" in text and "PRESCRIPTION" in text


def test_unreadable_doc_asks_reupload_and_is_not_reported_as_missing():
    decision = _run(
        {
            "member_id": "EMP004",
            "claim_category": "PHARMACY",
            "claimed_amount": 800,
            "documents": [
                {"file_id": "A", "actual_type": "PRESCRIPTION", "quality": "GOOD"},
                {"file_id": "B", "actual_type": "PHARMACY_BILL", "quality": "UNREADABLE"},
            ],
        }
    )
    assert decision.status == "BLOCKED"
    text = " ".join(decision.messages)
    assert "re-upload" in text.lower() and "PHARMACY_BILL" in text
    assert "requires a PHARMACY_BILL" not in text  # readability, not a missing-doc report


def test_patient_mismatch_surfaces_both_specific_names():
    decision = _run(
        {
            "member_id": "EMP001",
            "claim_category": "CONSULTATION",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "A", "actual_type": "PRESCRIPTION", "patient_name_on_doc": "Rajesh Kumar"},
                {"file_id": "B", "actual_type": "HOSPITAL_BILL", "patient_name_on_doc": "Arjun Mehta"},
            ],
        }
    )
    assert decision.status == "BLOCKED"
    text = " ".join(decision.messages)
    assert "Rajesh Kumar" in text and "Arjun Mehta" in text


def test_covered_dependent_name_is_accepted_not_flagged():
    # "Arjun Kumar" is DEP002, a covered dependent of EMP001 — must NOT mismatch.
    decision = _run(
        {
            "member_id": "EMP001",
            "claim_category": "CONSULTATION",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "A", "actual_type": "PRESCRIPTION", "patient_name_on_doc": "Arjun Kumar"},
                {
                    "file_id": "B",
                    "actual_type": "HOSPITAL_BILL",
                    "patient_name_on_doc": "Arjun Kumar",
                    # A real bill carries charges; without them the gate now (correctly)
                    # blocks as an unreadable/unusable bill, so give it usable content.
                    "content": {
                        "line_items": [{"description": "Treatment Charges", "amount": 1500}],
                        "total": 1500,
                    },
                },
            ],
        }
    )
    assert decision.status != "BLOCKED"
