"""Provider-agnostic LLM client protocol and extraction result schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ExtractionResult:
    """Structured output from one document extraction pass.

    Maps 1-to-1 with the ``extraction.<file_id>`` fact value so the gate and rule
    agents can consume either the fake or the real client's output identically.
    """

    file_id: str
    doc_type: str | None = None          # PRESCRIPTION | HOSPITAL_BILL | etc.
    readable: bool = True
    quality: str = "GOOD"                # GOOD | POOR | UNREADABLE
    patient_name: str | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    hospital_name: str | None = None
    date: str | None = None              # YYYY-MM-DD
    diagnosis: str | None = None
    treatment: str | None = None
    medicines: list[str] = field(default_factory=list)
    tests_ordered: list[str] = field(default_factory=list)
    line_items: list[dict[str, Any]] = field(default_factory=list)
    total_amount: float | None = None
    confidence: float = 1.0
    raw: dict[str, Any] = field(default_factory=dict)  # full LLM JSON for tracing


@runtime_checkable
class LLMClient(Protocol):
    """One method: extract a document from bytes and return a structured result."""

    async def extract(
        self,
        file_id: str,
        data: bytes,
        mime_type: str = "image/jpeg",
        hint_type: str | None = None,  # optional doc-type hint from the submission
    ) -> ExtractionResult: ...
