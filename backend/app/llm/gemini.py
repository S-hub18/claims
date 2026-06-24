"""Gemini vision extraction + reasoning client (model: gemini-2.5-flash, override with GEMINI_MODEL).

Uses the current ``google-genai`` SDK (not the deprecated ``google-generativeai``).
Structured JSON output via ``response_mime_type`` — no regex parsing of free text.

Every model call goes through ``_generate``, which retries transient failures
(429 quota, 5xx, network) with backoff and raises a typed ``LLMUnavailableError`` on
persistent failure — so a *system* outage is never silently returned as empty data.

Self-correction: if the first pass returns confidence < REREAD_THRESHOLD, a second
targeted pass re-reads the low-confidence fields. One retry maximum.

Extraction cache: sha256(bytes) → ExtractionResult so re-submitted docs don't burn
quota. The cache is in-memory for Stage 1; a Redis-backed cache replaces it in Part 8.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any

from google import genai
from google.genai import types

from .base import ExtractionResult

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
REREAD_THRESHOLD = 0.70
_MAX_RETRIES = 4  # transient 429/503 backoff: 1s, 2s, 4s, then give up


class LLMUnavailableError(RuntimeError):
    """Raised when the model call fails for a system reason (quota, network, 5xx) —
    i.e. NOT a document-quality problem. Callers must surface this distinctly from a
    genuine 'document unreadable' verdict, never silently treat it as low quality."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind  # "QUOTA" | "NETWORK" | "SERVER" | "UNKNOWN"


def _classify_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "resource_exhausted" in text or "429" in text or "quota" in text or "rate" in text:
        return "QUOTA"
    if "503" in text or "unavailable" in text or "500" in text or "internal" in text:
        return "SERVER"
    if "timeout" in text or "connection" in text or "network" in text:
        return "NETWORK"
    return "UNKNOWN"


def _is_retryable(exc: Exception) -> bool:
    return _classify_error(exc) in {"QUOTA", "SERVER", "NETWORK"}

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

CRITICAL ANTI-HALLUCINATION RULES — read carefully:
- ONLY report characters, numbers, and amounts you can LITERALLY SEE and read in the image.
- NEVER guess, infer, complete, or invent a value. If a line item, amount, name, or total
  is blurred, faint, cut off, or otherwise not clearly legible, DO NOT fabricate a
  plausible value — leave it out.
- If the image is blurry, low-resolution, dark, or the printed text is not crisply legible,
  set readable=false, quality=UNREADABLE (or POOR), and return EMPTY line_items — even if
  you can tell it is "a bill". Recognising the document TYPE is not the same as reading it.
- If you find yourself producing values that "seem reasonable" rather than values you can
  actually read, STOP and set readable=false instead. Inventing data is a critical failure.

Set confidence (0.0–1.0) to your TRUE certainty that every reported value matches the image.
Set readable=false and quality=UNREADABLE if you cannot clearly read the actual content."""


def _extraction_has_amounts(r: ExtractionResult) -> bool:
    """Any readable extraction that claims monetary amounts is worth the consistency check.

    We do NOT gate on doc_type: a blurred bill is frequently mislabelled UNKNOWN (not
    *BILL*) yet still carries a hallucinated total, and downstream normalisation retypes
    ANY charge-bearing document into a bill. Gating the guard on the doc-type label would
    let exactly those hallucinations through — so trigger on amounts alone."""
    return r.readable and (bool(r.line_items) or r.total_amount is not None)


def _close(x: float | None, y: float | None) -> bool:
    x, y = float(x or 0), float(y or 0)
    if x == 0 and y == 0:
        return True
    return abs(x - y) <= 0.02 * max(abs(x), abs(y))  # within 2%


def _line_map(r: ExtractionResult) -> dict[str, float]:
    """description (normalised) → amount, for per-line comparison across passes."""
    out: dict[str, float] = {}
    for li in r.line_items or []:
        desc = (li.get("description") or "").strip().lower()
        out[desc] = float(li.get("amount") or 0)
    return out


def _consistent(a: ExtractionResult, b: ExtractionResult) -> bool:
    """True if two independent extraction passes agree closely enough to be trusted.

    Genuine printed text reads identically every time; a fabricated read drifts between
    passes. Crucially we compare amounts PER LINE ITEM (matched by description), not just
    the summed total — a hallucinated bill can keep the same total while the individual
    amounts shuffle between lines (e.g. 150/180 ↔ 180/150, sum 450 both times). Checking
    only the sum would wrongly call that consistent. We require: same line count, same set
    of descriptions, every matched line's amount within tolerance, and the total within
    tolerance. A pass that collapsed to unreadable is itself a divergence.
    """
    if not b.readable:
        return False
    if len(a.line_items or []) != len(b.line_items or []):
        return False

    ma, mb = _line_map(a), _line_map(b)
    if set(ma) != set(mb):           # descriptions diverged between passes
        return False
    for desc, amt in ma.items():     # per-line amounts must agree
        if not _close(amt, mb[desc]):
            return False

    return _close(a.total_amount, b.total_amount)


def _as_unreadable(r: ExtractionResult) -> ExtractionResult:
    """Recast a result as unreadable so the gate asks for a clearer photo. Used when the
    self-consistency check fails — we cannot trust the numbers the model produced."""
    r.readable = False
    r.quality = "UNREADABLE"
    r.confidence = 0.0
    r.line_items = []
    r.total_amount = None
    r.raw = {**(r.raw or {}), "hallucination_guard": "inconsistent re-extraction"}
    return r


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
    """Gemini vision extraction + reasoning. Thread-safe; one instance per process."""

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

    async def _generate(self, **kwargs: Any) -> Any:
        """Single choke-point for every Gemini call. Retries transient failures
        (429 quota, 5xx, network) with exponential backoff, then raises a typed
        ``LLMUnavailableError`` so callers can distinguish a *system* failure from a
        document-quality verdict. Never silently returns empty."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await self._client.aio.models.generate_content(**kwargs)
            except Exception as exc:  # noqa: BLE001 — classified below, re-raised typed
                last_exc = exc
                if _is_retryable(exc) and attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2**attempt)  # 1s, 2s, 4s
                    continue
                kind = _classify_error(exc)
                raise LLMUnavailableError(str(exc), kind=kind) from exc
        kind = _classify_error(last_exc) if last_exc else "UNKNOWN"
        raise LLMUnavailableError(str(last_exc), kind=kind)

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

        result = await self._extract_once(file_id, data, mime_type, _SYSTEM_PROMPT)

        # Self-correction: low confidence → re-read with a more targeted prompt.
        if result.confidence < REREAD_THRESHOLD:
            reread_prompt = (
                _SYSTEM_PROMPT
                + "\n\nPrevious extraction had low confidence. Focus especially on: "
                "patient name, document date, total amount, and document type. "
                "Re-examine the image carefully."
            )
            result2 = await self._extract_once(file_id, data, mime_type, reread_prompt)
            # Keep whichever pass is more confident.
            if result2.confidence > result.confidence:
                result = result2

        # Hallucination guard (self-consistency). A blurred bill is the dangerous case:
        # the model can confidently FABRICATE line items/amounts (high confidence, GOOD
        # quality) instead of admitting it can't read them. No single signal catches this,
        # so for a money-bearing bill we re-extract with a DIFFERENT seed/temperature and
        # compare. Real printed text reads identically every time; fabrications are
        # unstable and diverge. If the two passes disagree, the read is untrustworthy —
        # mark it UNREADABLE so the gate asks for a clearer photo rather than adjudicating
        # invented numbers.
        if _extraction_has_amounts(result):
            verify = await self._extract_once(
                file_id, data, mime_type, _SYSTEM_PROMPT, seed=7919, temperature=0.6
            )
            if not _consistent(result, verify):
                result = _as_unreadable(result)

        self._cache[ck] = result
        return result

    async def _extract_once(
        self,
        file_id: str,
        data: bytes,
        mime_type: str,
        prompt: str,
        *,
        seed: int = 42,
        temperature: float = 0.1,
    ) -> ExtractionResult:
        image_part = types.Part.from_bytes(data=data, mime_type=mime_type)
        response = await self._generate(
            model=MODEL,
            contents=[image_part, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_EXTRACTION_SCHEMA,
                temperature=temperature,
                seed=seed,
            ),
        )
        raw = json.loads(response.text)
        return _parse(raw, file_id)

    async def reason(
        self,
        prompt: str,
        tool_declarations: list[dict],
        tool_executor: dict,
        response_schema: dict,
        on_tool_call=None,
        max_tool_rounds: int = 4,
    ) -> dict:
        """Tool-calling reasoning loop. Gemini decides which tools to call; we execute them.

        Gemini function-calling: model sees tool schemas, calls them, we run the Python
        functions, feed results back, repeat until model returns a final structured answer.
        """
        from google.genai import types as _types

        fn_declarations = [
            _types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("parameters"),
            )
            for t in tool_declarations
        ]
        tool = _types.Tool(function_declarations=fn_declarations)

        contents: list = [
            _types.Content(role="user", parts=[_types.Part(text=prompt)])
        ]

        for _ in range(max_tool_rounds):
            response = await self._generate(
                model=MODEL,
                contents=contents,
                config=_types.GenerateContentConfig(tools=[tool], temperature=0.1, seed=42),
            )
            candidate = response.candidates[0]
            fn_calls = [
                p.function_call
                for p in candidate.content.parts
                if hasattr(p, "function_call") and p.function_call
            ]
            if not fn_calls:
                break

            contents.append(candidate.content)

            fn_response_parts = []
            for fc in fn_calls:
                fn_name = fc.name
                fn_args = dict(fc.args) if fc.args else {}
                fn_result = tool_executor[fn_name](fn_args)
                if on_tool_call:
                    on_tool_call(fn_name, fn_args, fn_result)
                fn_response_parts.append(
                    _types.Part(
                        function_response=_types.FunctionResponse(
                            name=fn_name,
                            response={"result": fn_result},
                        )
                    )
                )
            contents.append(_types.Content(role="user", parts=fn_response_parts))

        final = await self._generate(
            model=MODEL,
            contents=contents,
            config=_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.1,
                seed=42,
            ),
        )
        return json.loads(final.text)

    async def reason_simple(self, prompt: str, response_schema: dict) -> dict:
        """Single-turn structured response with no tool calls."""
        response = await self._generate(
            model=MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.1,
                seed=42,
            ),
        )
        return json.loads(response.text)
