"""Anthropic (Claude) vision extraction client.

A drop-in replacement for ``GeminiClient`` on the *extraction* path: same
``extract()`` signature, same ``ExtractionResult`` output, same anti-hallucination
guards (low-confidence re-read + self-consistency re-extraction). It deliberately
does NOT implement ``reason`` / ``reason_simple`` — ``PolicyReasonerAgent`` checks
``hasattr(llm, "reason")`` and falls back to its deterministic keyword baseline, so
wiring this client keeps adjudication reasoning offline-deterministic (and the demo
12/12) while real uploaded files are read by Claude.

Reuses the extraction schema, system prompt, parser, and hallucination-guard helpers
from ``gemini`` so the two providers behave identically.

Model: claude-haiku-4-5 by default; override with ANTHROPIC_MODEL.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os

import anthropic

from .base import ExtractionResult
from .gemini import (
    REREAD_THRESHOLD,
    LLMUnavailableError,
    _EXTRACTION_SCHEMA,
    _SYSTEM_PROMPT,
    _as_unreadable,
    _consistent,
    _extraction_has_amounts,
    _parse,
)

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_MAX_RETRIES = 4
_MAX_TOKENS = 1500
_SEGMENT_MAX_TOKENS = 4096
_IMAGE_MEDIA = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# The 7 document types seen across the test cases, plus UNKNOWN. The combined-PDF
# splitter classifies each detected document against this set.
_DOC_TYPE_ENUM = [
    "PRESCRIPTION",
    "HOSPITAL_BILL",
    "PHARMACY_BILL",
    "LAB_REPORT",
    "DIAGNOSTIC_REPORT",
    "DISCHARGE_SUMMARY",
    "DENTAL_REPORT",
    "UNKNOWN",
]

# Schema for the splitter: one entry per distinct document found in the PDF. Each entry
# is an extraction (same fields as _EXTRACTION_SCHEMA) plus the 1-indexed page span it
# occupies — a document may span several consecutive pages (a continuation).
_SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_type": {"type": "string", "enum": _DOC_TYPE_ENUM},
                    "page_start": {"type": "integer"},
                    "page_end": {"type": "integer"},
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
                "required": ["doc_type", "page_start", "page_end", "readable", "quality", "confidence"],
            },
        }
    },
    "required": ["documents"],
}

_SEGMENT_PROMPT = (
    _SYSTEM_PROMPT
    + "\n\nThis file may be SEVERAL separate documents combined into one PDF (e.g. a "
    "prescription followed by a hospital bill followed by a lab report). Identify EVERY "
    "distinct document and record one entry per document via record_documents.\n"
    "- Pages are 1-indexed. Give each document's page_start and page_end.\n"
    "- A single document can span multiple consecutive pages (a continuation — e.g. a bill "
    "whose line items run onto the next page). Group those pages into ONE document; do NOT "
    "split a continuation into separate documents.\n"
    "- Classify each document's doc_type from the allowed set; use UNKNOWN if genuinely "
    "unclear. Extract each document's fields from ITS pages only.\n"
    "- If the file is actually a single document, return exactly one entry spanning all pages."
)


def _kind(exc: Exception) -> str:
    if isinstance(exc, anthropic.RateLimitError):
        return "QUOTA"
    if isinstance(exc, anthropic.APIConnectionError):
        return "NETWORK"
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return "SERVER" if status >= 500 else "CLIENT"
    return "UNKNOWN"


class AnthropicClient:
    """Claude vision extraction. Thread-safe; one instance per process."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Export it or pass api_key= to AnthropicClient()."
            )
        self._client = anthropic.AsyncAnthropic(api_key=key)
        self._model = MODEL
        self._cache: dict[str, ExtractionResult] = {}
        self._seg_cache: dict[str, list[ExtractionResult]] = {}

    async def _create(self, **kwargs):
        """Single choke-point. Retries transient failures (429/5xx/network) with
        backoff, then raises a typed ``LLMUnavailableError`` so the extractor can
        surface a *system* failure distinctly from a document-quality verdict."""
        last: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await self._client.messages.create(**kwargs)
            except (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.InternalServerError,
            ) as exc:
                last = exc
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                raise LLMUnavailableError(str(exc), kind=_kind(exc)) from exc
            except anthropic.APIStatusError as exc:
                if 500 <= (exc.status_code or 0) < 600 and attempt < _MAX_RETRIES - 1:
                    last = exc
                    await asyncio.sleep(2**attempt)
                    continue
                raise LLMUnavailableError(str(exc), kind=_kind(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — re-raised typed
                raise LLMUnavailableError(str(exc), kind="UNKNOWN") from exc
        raise LLMUnavailableError(str(last) if last else "unknown", kind=_kind(last) if last else "UNKNOWN")

    def _doc_block(self, data: bytes, mime_type: str) -> dict:
        b64 = base64.standard_b64encode(data).decode("ascii")
        if (mime_type or "").lower() == "application/pdf":
            return {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            }
        media = mime_type if mime_type in _IMAGE_MEDIA else "image/jpeg"
        return {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}}

    async def _extract_once(
        self, file_id: str, data: bytes, mime_type: str, prompt: str, *, temperature: float = 0.1
    ) -> ExtractionResult:
        resp = await self._create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            temperature=temperature,
            system=prompt,
            tools=[
                {
                    "name": "record_extraction",
                    "description": "Record the structured fields read from the document.",
                    "input_schema": _EXTRACTION_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": "record_extraction"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        self._doc_block(data, mime_type),
                        {
                            "type": "text",
                            "text": (
                                "Read this document and record every field you can literally see "
                                "via record_extraction. Obey the anti-hallucination rules strictly."
                            ),
                        },
                    ],
                }
            ],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_extraction":
                return _parse(dict(block.input), file_id)
        # No structured tool call returned → treat as unreadable rather than inventing data.
        return ExtractionResult(
            file_id=file_id, readable=False, quality="UNREADABLE", confidence=0.0,
            raw={"note": "no record_extraction tool_use returned"},
        )

    async def extract(
        self,
        file_id: str,
        data: bytes,
        mime_type: str = "image/jpeg",
        hint_type: str | None = None,
    ) -> ExtractionResult:
        ck = hashlib.sha256(data).hexdigest()
        if ck in self._cache:
            return self._cache[ck]

        result = await self._extract_once(file_id, data, mime_type, _SYSTEM_PROMPT)

        # Self-correction: low confidence → one targeted re-read; keep the more confident pass.
        if result.confidence < REREAD_THRESHOLD:
            result2 = await self._extract_once(
                file_id, data, mime_type,
                _SYSTEM_PROMPT
                + "\n\nPrevious extraction had low confidence. Re-examine carefully: patient "
                "name, document date, total amount, and document type.",
            )
            if result2.confidence > result.confidence:
                result = result2

        # Hallucination guard: a money-bearing read is re-extracted at a higher temperature;
        # genuine printed text reads identically, fabrications drift. Disagreement → UNREADABLE.
        if _extraction_has_amounts(result):
            verify = await self._extract_once(file_id, data, mime_type, _SYSTEM_PROMPT, temperature=0.6)
            if not _consistent(result, verify):
                result = _as_unreadable(result)

        self._cache[ck] = result
        return result

    async def segment(
        self, file_id: str, data: bytes, mime_type: str = "application/pdf"
    ) -> list[ExtractionResult]:
        """Split a (possibly combined) PDF into its constituent documents.

        Returns one ExtractionResult per distinct document, in page order. A document may
        span several consecutive pages (a continuation) — those are grouped into one entry.
        When the file is a single document, defers to the guarded ``extract()`` so the
        anti-hallucination checks still apply; only genuinely multi-document files use the
        one-pass split. Page spans are stashed in each result's ``raw`` for the trace.
        """
        ck = hashlib.sha256(data).hexdigest()
        if ck in self._seg_cache:
            return self._seg_cache[ck]

        resp = await self._create(
            model=self._model,
            max_tokens=_SEGMENT_MAX_TOKENS,
            temperature=0.1,
            system=_SEGMENT_PROMPT,
            tools=[
                {
                    "name": "record_documents",
                    "description": "Record every distinct document found in the PDF, in page order.",
                    "input_schema": _SEGMENT_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": "record_documents"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        self._doc_block(data, mime_type),
                        {
                            "type": "text",
                            "text": (
                                "Identify each separate document in this PDF and record it via "
                                "record_documents — one entry per document, grouping continuation "
                                "pages. Obey the anti-hallucination rules strictly."
                            ),
                        },
                    ],
                }
            ],
        )

        entries: list[dict] = []
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_documents":
                entries = list(block.input.get("documents") or [])
                break

        # Single document (or the model returned nothing useful) → guarded single extract.
        if len(entries) <= 1:
            result = await self.extract(file_id, data, mime_type)
            if entries:
                e = entries[0]
                result.raw = {**(result.raw or {}), "page_start": e.get("page_start"), "page_end": e.get("page_end")}
            out = [result]
            self._seg_cache[ck] = out
            return out

        out = []
        for i, entry in enumerate(entries):
            res = _parse(dict(entry), f"{file_id}#{i}")
            res.raw = {
                **(res.raw or {}),
                "page_start": entry.get("page_start"),
                "page_end": entry.get("page_end"),
                "segmented_from": file_id,
            }
            out.append(res)
        self._seg_cache[ck] = out
        return out
