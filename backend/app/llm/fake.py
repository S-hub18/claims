"""FakeLLMClient — returns inline ``content`` from the submission document.

Used by the deterministic eval suite (12/12 cases, zero API calls). The test cases
embed each document's content directly in the JSON, so the fake client just lifts it
into an ExtractionResult with the same shape the real Gemini client would return.
This keeps Stage 1 fully offline and the eval floor enforced in CI.
"""

from __future__ import annotations

from typing import Any

from .base import ExtractionResult


class FakeLLMClient:
    """Offline extraction — reads ``_inline`` content injected by DocExtractor."""

    def __init__(self, submissions: dict[str, dict[str, Any]] | None = None) -> None:
        # submissions maps file_id → the raw document dict from the test case.
        # DocExtractor injects this so FakeLLMClient never needs the actual bytes.
        self._docs: dict[str, dict[str, Any]] = submissions or {}

    def register(self, file_id: str, doc: dict[str, Any]) -> None:
        self._docs[file_id] = doc

    async def extract(
        self,
        file_id: str,
        data: bytes,
        mime_type: str = "image/jpeg",
        hint_type: str | None = None,
    ) -> ExtractionResult:
        doc = self._docs.get(file_id, {})
        content = doc.get("content") or {}
        quality = doc.get("quality", "GOOD")
        readable = quality != "UNREADABLE"
        # Extracted from the document body only — the external patient_name_on_doc
        # hint and the file_name must have no impact on the decision.
        patient_name = content.get("patient_name")

        return ExtractionResult(
            file_id=file_id,
            doc_type=doc.get("actual_type"),
            readable=readable,
            quality=quality,
            patient_name=patient_name,
            doctor_name=content.get("doctor_name"),
            doctor_registration=content.get("doctor_registration"),
            hospital_name=content.get("hospital_name"),
            date=content.get("date"),
            diagnosis=content.get("diagnosis"),
            treatment=content.get("treatment"),
            medicines=content.get("medicines") or [],
            tests_ordered=content.get("tests_ordered") or [],
            line_items=content.get("line_items") or [],
            total_amount=content.get("total"),
            confidence=1.0,
            raw=content,
        )
