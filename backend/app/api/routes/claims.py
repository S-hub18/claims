"""Claims endpoints — submit, poll, and stream.

  POST /claims          → {claim_id, status:"processing"} in milliseconds
  GET  /claims/{id}     → current decision (or status:"processing")
  GET  /claims/{id}/stream → SSE — one event per blackboard fact + final decision event

Adjudication runs as a FastAPI BackgroundTask. On completion, all facts + the decision
are persisted to DB (when DATABASE_URL is set). SSE uses Redis pub/sub when REDIS_URL
is set; otherwise falls back to asyncio.Queue for single-process deploys.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.schemas import ClaimSubmission, DecisionResponse, FactEvent, SubmitResponse
from app.api.store import ClaimStore
from app.config import Settings, get_settings
from app.decision import Decision
from app.engine import run_claim
from app.llm.gemini import GeminiClient
from app.policy import Policy

router = APIRouter(prefix="/claims", tags=["claims"])


def _decimal_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, bytes):
        return f"<binary {len(obj)}b>"
    raise TypeError(f"Not serialisable: {type(obj)}")


def _json_safe(obj: Any) -> Any:
    """Strip values the HTTP layer can't encode out of a fact's value.

    The ``submission`` fact carries the raw document bytes of any uploaded file, and
    financial facts carry Decimals. Both must be made JSON-safe before a fact is sent
    in DecisionResponse, otherwise the whole GET 500s (and the browser reports it as a
    CORS error). Mirrors ``_decimal_default`` but recurses through the value tree."""
    if isinstance(obj, bytes):
        return f"<binary {len(obj)}b>"
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _decision_to_dict(claim_id: str, decision: Decision) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "status": decision.status,
        "approved_amount": str(decision.approved_amount) if decision.approved_amount else None,
        "rejection_reasons": decision.rejection_reasons,
        "messages": decision.messages,
        "notes": decision.notes,
        "confidence": decision.confidence,
        "fact_count": len(decision.trace),
    }


def _segment_to_doc(res: Any, base_name: str) -> dict[str, Any]:
    """Turn one segmented ExtractionResult into a submission document carrying inline
    content, so the offline content-lift extractor consumes it without re-calling the LLM."""
    raw = res.raw or {}
    span = ""
    if raw.get("page_start") is not None:
        ps, pe = raw.get("page_start"), raw.get("page_end")
        span = f" · p{ps}" + (f"-{pe}" if pe and pe != ps else "")
    return {
        "file_id": res.file_id,
        "file_name": f"{base_name} — {res.doc_type or 'document'}{span}",
        "actual_type": res.doc_type,
        "quality": res.quality,
        "content": {
            "patient_name": res.patient_name,
            "doctor_name": res.doctor_name,
            "doctor_registration": res.doctor_registration,
            "hospital_name": res.hospital_name,
            "date": res.date,
            "diagnosis": res.diagnosis,
            "treatment": res.treatment,
            "medicines": res.medicines,
            "tests_ordered": res.tests_ordered,
            "line_items": res.line_items,
            "total": res.total_amount,
        },
    }


async def _expand_combined_pdfs(
    submission: dict[str, Any], llm_client: Any
) -> dict[str, Any]:
    """Replace each uploaded PDF with its constituent documents (one combined PDF may hold
    a prescription + bill + lab report). A single-document PDF expands to one entry. No-op
    when the client can't segment, or for inline-content (demo/test) documents."""
    if llm_client is None or not hasattr(llm_client, "segment"):
        return submission
    out: list[dict[str, Any]] = []
    changed = False
    for d in submission.get("documents", []):
        is_pdf = (d.get("mime_type") or "").lower() == "application/pdf"
        if d.get("data") and not d.get("content") and is_pdf:
            try:
                segments = await llm_client.segment(
                    file_id=d["file_id"], data=d["data"], mime_type="application/pdf"
                )
            except Exception:
                segments = None
            if segments:
                base = d.get("file_name") or d["file_id"]
                out.extend(_segment_to_doc(s, base) for s in segments)
                changed = True
                continue
        out.append(d)
    return {**submission, "documents": out} if changed else submission


async def _adjudicate_bg(
    claim_id: str,
    submission_dict: dict[str, Any],
    store: ClaimStore,
    policy: Policy,
    settings: Settings,
) -> None:
    record = store.get(claim_id)
    if record is None:
        return
    try:
        # Extraction provider: prefer Anthropic (Claude) when its key is set, else
        # Gemini, else None → pure-offline content-lift. A bad key never crashes the
        # claim: fall back to offline so the demo (inline content) still adjudicates.
        llm_client = None
        try:
            if settings.anthropic_api_key:
                from app.llm.anthropic_client import AnthropicClient
                llm_client = AnthropicClient(api_key=settings.anthropic_api_key)
            elif settings.gemini_api_key:
                llm_client = GeminiClient(api_key=settings.gemini_api_key)
        except Exception:
            llm_client = None
        # Split any combined PDF (multiple documents in one file) into its constituent
        # documents before adjudication, so each is gated/priced as its own document.
        submission_dict = await _expand_combined_pdfs(submission_dict, llm_client)
        decision = await run_claim(
            submission_dict,
            policy,
            llm_client=llm_client,
            on_post=store.on_post_hook(record),
        )
        store.finish(record, _decision_to_dict(claim_id, decision))
    except Exception as exc:
        store.fail(record, str(exc))

    # Bulk-persist facts + decision to DB (no-op when DATABASE_URL not set).
    await store.persist(record)


def _resolve_policy(override: dict[str, Any] | None, default: Policy) -> Policy:
    """Use the caller-supplied policy when it is present and well-formed;
    otherwise fall back to the server's default policy as a backup."""
    if not override:
        return default
    # The engine relies on these sections — a malformed upload silently falls back
    # rather than failing the claim.
    if not all(k in override for k in ("coverage", "document_requirements", "opd_categories")):
        return default
    try:
        return Policy(override)
    except Exception:
        return default


@router.post("", response_model=SubmitResponse, status_code=202)
async def submit_claim(
    body: ClaimSubmission,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SubmitResponse:
    store: ClaimStore = request.app.state.store
    policy: Policy = _resolve_policy(body.policy_override, request.app.state.policy)
    claim_id = str(uuid.uuid4())
    store.create(claim_id)

    submission = body.to_engine_dict()
    # Real-time velocity: for a claimant NOT on the policy roster (the custom flow), feed
    # the member's previously-submitted claims as history and record this one, so repeated
    # submissions for the same member accumulate and trip the velocity rule on their own.
    # Roster members (the seeded demo cases) are left alone and stay deterministic.
    roster = {(m.get("member_id") or "") for m in policy.members()}
    if body.member_id and body.member_id not in roster:
        # Sandbox the ledger per browser session so concurrent evaluators are isolated.
        ledger_key = f"{body.client_session or 'anon'}:{body.member_id}"
        prior = store.ledger_history(ledger_key)
        if prior:
            submission["claims_history"] = [*prior, *submission.get("claims_history", [])]
        store.record_in_ledger(ledger_key, body.treatment_date, body.claimed_amount)

    background_tasks.add_task(_adjudicate_bg, claim_id, submission, store, policy, settings)
    return SubmitResponse(claim_id=claim_id)


@router.get("/{claim_id}", response_model=DecisionResponse)
async def get_claim(claim_id: str, request: Request) -> DecisionResponse:
    store: ClaimStore = request.app.state.store
    # get_or_load falls back to DB on a memory miss (restart-resilience).
    record = await store.get_or_load(claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id!r} not found")
    if record.status == "processing":
        return DecisionResponse(
            claim_id=claim_id, status="processing", fact_count=len(record.facts)
        )
    d = record.decision or {}
    return DecisionResponse(
        claim_id=claim_id,
        status=d.get("status", record.status),
        approved_amount=d.get("approved_amount"),
        rejection_reasons=d.get("rejection_reasons", []),
        messages=d.get("messages", []),
        notes=d.get("notes", []),
        confidence=d.get("confidence"),
        fact_count=len(record.facts),
        # Replay the whole trace once the claim has settled — the lifecycle view reads
        # this to render every step. Sanitise each value first: the submission fact
        # holds uploaded-file bytes and financial facts hold Decimals, neither of which
        # the JSON response can encode.
        facts=[FactEvent(**{**f, "value": _json_safe(f.get("value"))}) for f in record.facts],
    )


@router.get("/{claim_id}/stream")
async def stream_claim(claim_id: str, request: Request) -> StreamingResponse:
    store: ClaimStore = request.app.state.store
    record = store.get(claim_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id!r} not found")

    redis_client = getattr(request.app.state, "redis_client", None)

    async def _event_stream():
        # Replay already-posted facts first (late / reconnecting clients).
        for fact_dict in list(record.facts):
            yield f"event: fact\ndata: {json.dumps(fact_dict, default=_decimal_default)}\n\n"

        if record.status == "completed":
            yield f"event: decision\ndata: {json.dumps(record.decision, default=_decimal_default)}\n\n"
            return

        if redis_client is not None:
            # Redis pub/sub path — works across processes and restarts.
            async with redis_client.pubsub() as ps:
                await ps.subscribe(f"claims:{claim_id}")
                while True:
                    if await request.is_disconnected():
                        break
                    msg = await ps.get_message(
                        ignore_subscribe_messages=True, timeout=30.0
                    )
                    if msg is None:
                        yield ": keepalive\n\n"
                        continue
                    data = json.loads(msg["data"])
                    if data.get("__done"):
                        yield f"event: decision\ndata: {json.dumps(data['decision'], default=_decimal_default)}\n\n"
                        break
                    yield f"event: fact\ndata: {json.dumps(data, default=_decimal_default)}\n\n"
        else:
            # asyncio.Queue fallback — single-process only (local dev + tests).
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(record.queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is ClaimStore.DONE:
                    yield f"event: decision\ndata: {json.dumps(record.decision, default=_decimal_default)}\n\n"
                    break
                yield f"event: fact\ndata: {json.dumps(item, default=_decimal_default)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
