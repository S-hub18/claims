"""FastAPI layer tests — submit, poll, and SSE stream.

Uses httpx AsyncClient (ships with FastAPI's testclient). All claims use inline
content so zero LLM calls; the full adjudication engine runs for real.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# A minimal clean CONSULTATION case (mirrors TC004, no network discount).
CLEAN_SUBMISSION = {
    "member_id": "EMP001",
    "policy_id": "PLUM_GHI_2024",
    "claim_category": "CONSULTATION",
    "treatment_date": "2024-11-01",
    "claimed_amount": 1500,
    "documents": [
        {
            "file_id": "T001",
            "actual_type": "PRESCRIPTION",
            "content": {
                "doctor_name": "Dr. Arun Sharma",
                "doctor_registration": "KA/45678/2015",
                "patient_name": "Rajesh Kumar",
                "date": "2024-11-01",
                "diagnosis": "Viral Fever",
            },
        },
        {
            "file_id": "T002",
            "actual_type": "HOSPITAL_BILL",
            "content": {
                "hospital_name": "City Clinic",
                "patient_name": "Rajesh Kumar",
                "line_items": [
                    {"description": "Consultation Fee", "amount": 1500}
                ],
                "total": 1500,
            },
        },
    ],
}

BLOCKED_SUBMISSION = {
    "member_id": "EMP001",
    "policy_id": "PLUM_GHI_2024",
    "claim_category": "CONSULTATION",
    "treatment_date": "2024-11-01",
    "claimed_amount": 1500,
    "documents": [
        {"file_id": "T003", "actual_type": "PRESCRIPTION"},
        {"file_id": "T004", "actual_type": "PRESCRIPTION"},  # no HOSPITAL_BILL
    ],
}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /claims
# ---------------------------------------------------------------------------

def test_submit_returns_claim_id_immediately(client):
    r = client.post("/claims", json=CLEAN_SUBMISSION)
    assert r.status_code == 202
    body = r.json()
    assert "claim_id" in body
    assert body["status"] == "processing"
    assert len(body["claim_id"]) == 36  # UUID


def test_submit_unknown_member_still_returns_claim_id(client):
    submission = dict(CLEAN_SUBMISSION, member_id="NOPE")
    r = client.post("/claims", json=submission)
    assert r.status_code == 202


# ---------------------------------------------------------------------------
# GET /claims/{id}
# ---------------------------------------------------------------------------

def test_get_missing_claim_returns_404(client):
    r = client.get("/claims/does-not-exist")
    assert r.status_code == 404


def test_get_claim_after_adjudication_returns_decision(client):
    r = client.post("/claims", json=CLEAN_SUBMISSION)
    claim_id = r.json()["claim_id"]

    # TestClient runs background tasks synchronously before returning from post,
    # so the claim is already adjudicated by the time we GET it.
    r2 = client.get(f"/claims/{claim_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "APPROVED"
    assert body["approved_amount"] == "1350"  # 1500 − 10% copay
    assert body["confidence"] is not None


def test_get_blocked_claim(client):
    r = client.post("/claims", json=BLOCKED_SUBMISSION)
    claim_id = r.json()["claim_id"]
    r2 = client.get(f"/claims/{claim_id}")
    assert r2.json()["status"] == "BLOCKED"


def test_get_rejected_claim(client):
    submission = {
        "member_id": "EMP005",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-15",
        "claimed_amount": 3000,
        "documents": [
            {"file_id": "T005", "actual_type": "PRESCRIPTION",
             "content": {"patient_name": "Vikram Joshi", "diagnosis": "Type 2 Diabetes Mellitus"}},
            {"file_id": "T006", "actual_type": "HOSPITAL_BILL",
             "content": {"patient_name": "Vikram Joshi", "total": 3000}},
        ],
    }
    r = client.post("/claims", json=submission)
    claim_id = r.json()["claim_id"]
    r2 = client.get(f"/claims/{claim_id}")
    body = r2.json()
    assert body["status"] == "REJECTED"
    assert "WAITING_PERIOD" in body["rejection_reasons"]


# ---------------------------------------------------------------------------
# GET /claims/{id}/stream (SSE)
# ---------------------------------------------------------------------------

def test_sse_stream_emits_facts_and_decision(client):
    r = client.post("/claims", json=CLEAN_SUBMISSION)
    claim_id = r.json()["claim_id"]

    # Collect (event_type, payload) pairs. SSE format:
    #   event: <type>\n
    #   data: <json>\n\n
    collected: list[tuple[str, dict]] = []
    with client.stream("GET", f"/claims/{claim_id}/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        current_event = "message"
        for line in resp.iter_lines():
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                collected.append((current_event, payload))
                if current_event == "decision":
                    break  # got the decision data — done
                current_event = "message"  # reset for next event

    fact_events    = [p for evt, p in collected if evt == "fact"]
    decision_events = [p for evt, p in collected if evt == "decision"]

    assert len(fact_events) > 0, "expected at least one fact event"
    assert any(e.get("key") == "submission" for e in fact_events)
    assert len(decision_events) == 1, "expected exactly one decision event"
    assert decision_events[0]["status"] == "APPROVED"


def test_sse_stream_missing_claim_returns_404(client):
    r = client.get("/claims/no-such-id/stream")
    assert r.status_code == 404
