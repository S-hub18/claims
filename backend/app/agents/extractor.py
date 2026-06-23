"""DocExtractor — turn one uploaded document into one ``extraction.<file_id>`` fact.

Two modes, same fact shape:

  Offline (Stage 1 / test):  ``llm_client`` is None or a FakeLLMClient.
      The test case carries each document's metadata/content inline (PRD §8.4), so
      extraction is deterministic and the suite runs with zero API calls.

  Live (Part 7+):  ``llm_client`` is a GeminiClient (or any LLMClient).
      The document ``data`` bytes are passed to the client; the result is normalised
      into the same fact value the gate and rule agents consume.

One extractor per document (not one for all) so each document resolves independently —
which lets the live board (Part 8) stream per-document progress, and lets the gate wait
on exactly the set of documents this claim carries.
"""

from __future__ import annotations

from typing import Any

from app.blackboard import Agent, Blackboard, Fact
from app.llm.base import ExtractionResult, LLMClient
from app.policy import Policy


def _normalized_doc_type(doc_type: str | None, line_items: Any, total: Any) -> str | None:
    """A document that itemises charges and a total IS a bill, whatever the model labelled
    it. Vision models routinely mislabel a real bill as DENTAL_REPORT / LAB_REPORT / etc.;
    five downstream consumers (the gate, semantic mapper, financial agents, cross-checks)
    identify "the bill" by a ``*BILL`` doc_type, so a mislabel would lose the bill entirely.
    Retype charge-bearing documents to HOSPITAL_BILL; leave charge-less reports untouched
    (a genuine report with no charges still correctly fails the required-bill gate)."""
    has_charges = bool(line_items) or total is not None
    if has_charges and not (doc_type or "").upper().endswith("BILL"):
        return "HOSPITAL_BILL"
    return doc_type


def _result_to_value(result: ExtractionResult) -> dict[str, Any]:
    """Normalise an ExtractionResult into the extraction fact's value dict."""
    return {
        "file_id": result.file_id,
        "doc_type": _normalized_doc_type(
            result.doc_type, result.line_items, result.total_amount
        ),
        "readable": result.readable,
        "quality": result.quality,
        "patient_name": result.patient_name,
        "content": {
            "doctor_name": result.doctor_name,
            "doctor_registration": result.doctor_registration,
            "hospital_name": result.hospital_name,
            "patient_name": result.patient_name,
            "date": result.date,
            "diagnosis": result.diagnosis,
            "treatment": result.treatment,
            "medicines": result.medicines,
            "tests_ordered": result.tests_ordered,
            "line_items": result.line_items,
            "total": result.total_amount,
        },
    }


class DocExtractor(Agent):
    reads = ["submission"]

    def __init__(
        self,
        file_id: str,
        policy: Policy | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.file_id = file_id
        self.policy = policy
        self.llm_client = llm_client
        self.name = f"extractor.{file_id}"
        self.writes = f"extraction.{file_id}"

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        doc = next(
            (d for d in submission.get("documents", []) if d.get("file_id") == self.file_id),
            None,
        )
        if doc is None:
            return Fact(
                key=self.writes,
                value={"file_id": self.file_id, "found": False},
                author=self.name,
                degraded=True,
            )

        # Live path: real bytes in the document → call the LLM client.
        if self.llm_client is not None and doc.get("data"):
            data: bytes = doc["data"]
            mime = doc.get("mime_type", "image/jpeg")
            hint = doc.get("actual_type")
            try:
                result = await self.llm_client.extract(
                    file_id=self.file_id, data=data, mime_type=mime, hint_type=hint
                )
            except Exception as exc:
                # A *system* failure (quota/network/5xx), NOT a document-quality verdict.
                # We must surface this distinctly — never let it masquerade as an
                # unreadable document, and never let downstream agents adjudicate on
                # empty extraction data. The aggregator short-circuits on system_error.
                kind = getattr(exc, "kind", "UNKNOWN")
                friendly = {
                    "QUOTA": "The document-reading service is over its quota right now.",
                    "NETWORK": "Could not reach the document-reading service.",
                    "SERVER": "The document-reading service returned an error.",
                }.get(kind, "The document-reading service failed.")
                return Fact(
                    key=self.writes,
                    value={
                        "file_id": self.file_id,
                        "system_error": True,
                        "error_kind": kind,
                        "message": f"{friendly} ({exc})",
                        "readable": None,  # unknown — NOT a readability verdict
                    },
                    author=self.name,
                    degraded=True,
                )
            return Fact(
                key=self.writes,
                value=_result_to_value(result),
                author=self.name,
                confidence=result.confidence,
            )

        # FakeLLMClient path: register the inline doc so the client can look it up,
        # then call extract() with empty bytes (FakeLLMClient ignores bytes).
        if self.llm_client is not None and hasattr(self.llm_client, "register"):
            self.llm_client.register(self.file_id, doc)
            result = await self.llm_client.extract(file_id=self.file_id, data=b"")
            return Fact(
                key=self.writes,
                value=_result_to_value(result),
                author=self.name,
                confidence=result.confidence,
            )

        # Pure offline path: no LLM client at all — lift inline content directly.
        content = doc.get("content") or {}
        quality = doc.get("quality", "GOOD")
        patient_name = doc.get("patient_name_on_doc") or content.get("patient_name")
        return Fact(
            key=self.writes,
            value={
                "file_id": self.file_id,
                "file_name": doc.get("file_name"),
                "doc_type": _normalized_doc_type(
                    doc.get("actual_type"), content.get("line_items"), content.get("total")
                ),
                "readable": quality != "UNREADABLE",
                "quality": quality,
                "patient_name": patient_name,
                "content": content or None,
            },
            author=self.name,
            confidence=1.0,
        )
