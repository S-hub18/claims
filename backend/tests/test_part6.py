"""Part 6 — fraud routing, graceful degradation, and run-to-run determinism.

Determinism (BE-2.7) is load-bearing for a multi-agent system: with concurrent agents
and a stateful-looking ledger, the same input must always produce the same fact-set and
the same decision, or the trace can't be trusted.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.engine import run_claim
from app.policy import Policy
from tests.eval.loader import load_cases


def _policy() -> Policy:
    return Policy.from_file(get_settings().policy_path)


def _run(submission: dict):
    return asyncio.run(run_claim(submission, _policy()))


def _case(case_id: str) -> dict:
    return next(c for c in load_cases() if c["case_id"] == case_id)["input"]


def test_same_day_velocity_routes_to_manual_review_not_reject():
    decision = _run(_case("TC009"))
    assert decision.status == "MANUAL_REVIEW"
    joined = " ".join(decision.messages).lower()
    assert "same day" in joined  # the specific signal is surfaced
    fraud = next(f for f in decision.trace if f.key == "verdict.fraud").value
    assert fraud["signals"]  # signals are recorded in the trace


def test_definitive_reject_outranks_fraud_flag():
    # A 4th same-day claim that is ALSO an excluded condition must REJECT, not MANUAL.
    submission = dict(_case("TC012"))
    submission["claims_history"] = [
        {"date": submission["treatment_date"], "amount": 100},
        {"date": submission["treatment_date"], "amount": 100},
        {"date": submission["treatment_date"], "amount": 100},
    ]
    decision = _run(submission)
    assert decision.status == "REJECTED"
    assert "EXCLUDED_CONDITION" in decision.rejection_reasons


def test_component_failure_degrades_not_crashes():
    decision = _run(_case("TC011"))
    assert decision.status == "APPROVED"  # pipeline continued
    clean = _run(_case("TC004"))
    assert decision.confidence < clean.confidence  # measurably lower
    note_text = " ".join(decision.notes).lower()
    assert "component" in note_text and "manual review" in note_text


def test_no_simulated_failure_keeps_full_confidence():
    decision = _run(_case("TC004"))
    assert decision.confidence > 0.85
    assert not any(f.degraded for f in decision.trace)


def test_determinism_50_runs_same_factset_and_decision():
    for case_id in ("TC004", "TC009", "TC012"):
        submission = _case(case_id)
        runs = [_run(submission) for _ in range(50)]
        keysets = {tuple(sorted(f.key for f in d.trace)) for d in runs}
        outcomes = {(d.status, str(d.approved_amount), tuple(d.rejection_reasons)) for d in runs}
        assert len(keysets) == 1, f"{case_id}: fact-set varied across runs"
        assert len(outcomes) == 1, f"{case_id}: decision varied across runs"
