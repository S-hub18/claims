"""Gemini 2.0 Flash vision extraction client.

Uses the current ``google-genai`` SDK (not the deprecated ``google-generativeai``).
Structured JSON output via ``response_mime_type`` — no regex parsing of free text.

Self-correction: if the first pass returns confidence < REREAD_THRESHOLD, a second
targeted pass re-reads the low-confidence fields. One retry maximum.

Extraction cache: sha256(bytes) → ExtractionResult so re-submitted docs don't burn
quota. The cache is in-memory for Stage 1; a Redis-backed cache replaces it in Part 8.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from google import genai
from google.genai import types

from .base import ExtractionResult

MODEL = "gemini-2.5-flash"
REREAD_THRESHOLD = 0.70

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {
            "type": "string",
            "enum": [
                "PRESCRIPTION",
                "HOSPITAL_BILL",
                "PHARMACY_BILL",
                "LAB_REPORT",
                "DENTAL_REPORT",
                "DISCHARGE_SUMMARY",
                "UNKNOWN",
            ],
        },
        "readable": {"type": "boolean"},
        "quality": {"type": "string", "enum": ["GOOD", "POOR", "UNREADABLE"]},
        "patient_name": {"type": "string"},
        "doctor_name": {"type": "string"},
        "doctor_registration": {"type": "string"},
        "hospital_name": {"type": "string"},
        "date": {"type": "string"},
        "diagnosis": {"type": "string"},
        "treatment": {"type": "string"},
        "medicines": {"type": "array", "items": {"type": "string"}},
        "tests_ordered": {"type": "array", "items": {"type": "string"}},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "amount": {"type": "number"},
                },
            },
        },
        "total_amount": {"type": "number"},
        "confidence": {"type": "number"},
    },
    "required": ["doc_type", "readable", "quality", "confidence"],
}

_SYSTEM_PROMPT = """You are an expert at extracting structured information from Indian
health insurance claim documents. Documents may be prescriptions, hospital bills, pharmacy
bills, lab reports, dental reports, or discharge summaries.

Extract every available field accurately. Indian medical documents often have:
- Mixed English and regional language text
- Handwritten sections alongside printed text
- Doctor registration numbers in format STATE/NUMBER/YEAR (e.g. KA/45678/2015)
- Amounts in Indian Rupees (₹ or Rs.)
- Dates in DD-Mon-YYYY or DD/MM/YYYY format — convert to YYYY-MM-DD

Be conservative: if a field is unclear or absent, omit it rather than guess.
Set confidence (0.0–1.0) to reflect your certainty across all extracted fields.
Set readable=false and quality=UNREADABLE only if the image is genuinely unreadable."""


def _parse(raw: dict[str, Any], file_id: str) -> ExtractionResult:
    return ExtractionResult(
        file_id=file_id,
        doc_type=raw.get("doc_type"),
        readable=raw.get("readable", True),
        quality=raw.get("quality", "GOOD"),
        patient_name=raw.get("patient_name") or None,
        doctor_name=raw.get("doctor_name") or None,
        doctor_registration=raw.get("doctor_registration") or None,
        hospital_name=raw.get("hospital_name") or None,
        date=raw.get("date") or None,
        diagnosis=raw.get("diagnosis") or None,
        treatment=raw.get("treatment") or None,
        medicines=raw.get("medicines") or [],
        tests_ordered=raw.get("tests_ordered") or [],
        line_items=raw.get("line_items") or [],
        total_amount=raw.get("total_amount"),
        confidence=float(raw.get("confidence", 0.8)),
        raw=raw,
    )


class GeminiClient:
    """Gemini 2.0 Flash vision extraction. Thread-safe; one instance per process."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Export it or pass api_key= to GeminiClient()."
            )
        self._client = genai.Client(api_key=key)
        self._cache: dict[str, ExtractionResult] = {}

    def _cache_key(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def extract(
        self,
        file_id: str,
        data: bytes,
        mime_type: str = "image/jpeg",
        hint_type: str | None = None,
    ) -> ExtractionResult:
        ck = self._cache_key(data)
        if ck in self._cache:
            return self._cache[ck]

        prompt = _SYSTEM_PROMPT
        if hint_type:
            prompt += f"\n\nThis document is expected to be a {hint_type}."

        result = await self._extract_once(file_id, data, mime_type, prompt)

        # Self-correction: low confidence → re-read with a more targeted prompt.
        if result.confidence < REREAD_THRESHOLD:
            reread_prompt = (
                prompt
                + "\n\nPrevious extraction had low confidence. Focus especially on: "
                "patient name, document date, total amount, and document type. "
                "Re-examine the image carefully."
            )
            result2 = await self._extract_once(file_id, data, mime_type, reread_prompt)
            # Keep whichever pass is more confident.
            if result2.confidence > result.confidence:
                result = result2

        self._cache[ck] = result
        return result

    async def _extract_once(
        self, file_id: str, data: bytes, mime_type: str, prompt: str
    ) -> ExtractionResult:
        image_part = types.Part.from_bytes(data=data, mime_type=mime_type)
        response = await self._client.aio.models.generate_content(
            model=MODEL,
            contents=[image_part, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_EXTRACTION_SCHEMA,
            ),
        )
        raw = json.loads(response.text)
        return _parse(raw, file_id)
