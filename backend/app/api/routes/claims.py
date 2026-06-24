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

from app.api.schemas import ClaimSubmission, DecisionResponse, SubmitResponse
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
    background_tasks.add_task(
        _adjudicate_bg, claim_id, body.to_engine_dict(), store, policy, settings
    )
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
