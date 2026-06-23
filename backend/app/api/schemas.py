"""Pydantic request/response schemas for the claims API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ── Submission input ──────────────────────────────────────────────────────────

class DocumentInput(BaseModel):
    file_id: str
    file_name: str | None = None
    actual_type: str | None = None          # PRESCRIPTION | HOSPITAL_BILL | etc.
    quality: str = "GOOD"
    patient_name_on_doc: str | None = None
    content: dict[str, Any] | None = None   # inline content (test / demo mode)
    data: str | None = None                 # base64-encoded bytes (real upload)
    mime_type: str = "image/jpeg"


class ClaimSubmission(BaseModel):
    member_id: str
    policy_id: str
    claim_category: str
    treatment_date: str
    claimed_amount: float
    hospital_name: str | None = None
    ytd_claims_amount: float | None = None
    claims_history: list[dict[str, Any]] = Field(default_factory=list)
    simulate_component_failure: bool = False
    documents: list[DocumentInput] = Field(default_factory=list)

    def to_engine_dict(self) -> dict[str, Any]:
        """Convert to the flat dict the engine's adjudicate() expects."""
        import base64

        docs = []
        for d in self.documents:
            doc: dict[str, Any] = {
                "file_id": d.file_id,
                "actual_type": d.actual_type,
                "quality": d.quality,
            }
            if d.file_name:
                doc["file_name"] = d.file_name
            if d.patient_name_on_doc:
                doc["patient_name_on_doc"] = d.patient_name_on_doc
            if d.content is not None:
                doc["content"] = d.content
            if d.data:
                doc["data"] = base64.b64decode(d.data)
                doc["mime_type"] = d.mime_type
            docs.append(doc)

        result: dict[str, Any] = {
            "member_id": self.member_id,
            "policy_id": self.policy_id,
            "claim_category": self.claim_category,
            "treatment_date": self.treatment_date,
            "claimed_amount": self.claimed_amount,
            "documents": docs,
        }
        if self.hospital_name:
            result["hospital_name"] = self.hospital_name
        if self.ytd_claims_amount is not None:
            result["ytd_claims_amount"] = self.ytd_claims_amount
        if self.claims_history:
            result["claims_history"] = self.claims_history
        if self.simulate_component_failure:
            result["simulate_component_failure"] = True
        return result


# ── Responses ─────────────────────────────────────────────────────────────────

class SubmitResponse(BaseModel):
    claim_id: str
    status: str = "processing"


class FactEvent(BaseModel):
    seq: int
    key: str
    value: Any
    author: str
    confidence: float | None
    degraded: bool
    derived_from: list[str]
    reason: str | None


class DecisionResponse(BaseModel):
    claim_id: str
    status: str       # BLOCKED | REJECTED | MANUAL_REVIEW | PARTIAL | APPROVED | processing
    approved_amount: Decimal | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    confidence: float | None = None
    fact_count: int = 0
    preliminary_decision: str | None = None


def fact_to_event(fact: Any) -> FactEvent:
    return FactEvent(
        seq=fact.seq,
        key=fact.key,
        value=fact.value,
        author=fact.author,
        confidence=fact.confidence,
        degraded=fact.degraded,
        derived_from=list(fact.derived_from),
        reason=fact.reason,
    )
