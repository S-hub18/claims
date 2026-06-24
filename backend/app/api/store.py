"""Claim store — in-memory primary path with optional DB + Redis backends.

In-memory (no env vars): works for local dev and all tests.
With DATABASE_URL:        facts + decision bulk-written to DB after adjudication.
With REDIS_URL:           facts published to ``claims:{id}`` channel in real-time;
                          SSE endpoint subscribes instead of polling asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

_DONE = object()  # sentinel for asyncio.Queue SSE path


def _serial(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(type(obj))


@dataclass
class ClaimRecord:
    claim_id: str
    status: str = "processing"
    facts: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class ClaimStore:
    DONE = _DONE

    def __init__(
        self,
        redis_client=None,     # redis.asyncio.Redis — optional
        session_factory=None,  # async_sessionmaker   — optional
    ) -> None:
        self._records: dict[str, ClaimRecord] = {}
        self._redis = redis_client
        self._session_factory = session_factory

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(self, claim_id: str) -> ClaimRecord:
        rec = ClaimRecord(claim_id=claim_id)
        self._records[claim_id] = rec
        return rec

    def get(self, claim_id: str) -> ClaimRecord | None:
        return self._records.get(claim_id)

    async def get_or_load(self, claim_id: str) -> ClaimRecord | None:
        """Memory-first; falls back to DB on a miss (restart-resilience)."""
        rec = self._records.get(claim_id)
        if rec is not None:
            return rec
        if self._session_factory is None:
            return None
        return await self._load_from_db(claim_id)

    # ── on_post hook (sync — called from inside the scheduler) ───────────────

    def on_post_hook(self, record: ClaimRecord):
        redis = self._redis
        claim_id = record.claim_id

        def _on_post(fact) -> None:
            fact_dict: dict[str, Any] = {
                "seq": fact.seq,
                "key": fact.key,
                "value": fact.value,
                "author": fact.author,
                "confidence": fact.confidence,
                "degraded": fact.degraded,
                "derived_from": list(fact.derived_from),
                "reason": fact.reason,
                # Cumulative ms from claim creation to when this fact landed — the
                # lifecycle/tester view shows it so a developer can see how long each
                # step took (e.g. LLM extraction vs an instant rule check).
                "t_ms": round((time.time() - record.created_at) * 1000, 1),
            }
            record.facts.append(fact_dict)
            record.queue.put_nowait(fact_dict)
            if redis is not None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        redis.publish(
                            f"claims:{claim_id}",
                            json.dumps(fact_dict, default=_serial),
                        )
                    )
                except RuntimeError:
                    pass  # no running loop (sync test context)

        return _on_post

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def finish(self, record: ClaimRecord, decision: dict[str, Any]) -> None:
        record.decision = decision
        record.status = "completed"
        record.queue.put_nowait(_DONE)
        if self._redis is not None:
            self._schedule_publish(
                f"claims:{record.claim_id}",
                json.dumps({"__done": True, "decision": decision}, default=_serial),
            )

    def fail(self, record: ClaimRecord, error: str) -> None:
        record.status = "failed"
        record.decision = {"error": error}
        record.queue.put_nowait(_DONE)
        if self._redis is not None:
            self._schedule_publish(
                f"claims:{record.claim_id}",
                json.dumps({"__done": True, "decision": {"error": error}}),
            )

    def _schedule_publish(self, channel: str, payload: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._redis.publish(channel, payload))
        except RuntimeError:
            pass

    # ── DB persistence (called after adjudication completes) ──────────────────

    async def persist(self, record: ClaimRecord) -> None:
        """Bulk-write claim + facts + decision to DB. No-op when DB not configured."""
        if self._session_factory is None:
            return

        from app.db.models import ClaimDecisionModel, ClaimModel, FactModel

        async with self._session_factory() as session:
            await session.merge(
                ClaimModel(
                    claim_id=record.claim_id,
                    status=record.status,
                    created_at=record.created_at,
                    updated_at=time.time(),
                )
            )
            for f in record.facts:
                session.add(
                    FactModel(
                        claim_id=record.claim_id,
                        seq=f["seq"],
                        key=f["key"],
                        author=f["author"],
                        value=f["value"],
                        confidence=f["confidence"],
                        degraded=f["degraded"],
                        derived_from=f.get("derived_from"),
                        reason=f.get("reason"),
                    )
                )
            if record.decision:
                d = record.decision
                await session.merge(
                    ClaimDecisionModel(
                        claim_id=record.claim_id,
                        status=d.get("status", record.status),
                        approved_amount=d.get("approved_amount"),
                        rejection_reasons=d.get("rejection_reasons", []),
                        messages=d.get("messages", []),
                        notes=d.get("notes", []),
                        confidence=d.get("confidence"),
                        fact_count=d.get("fact_count", len(record.facts)),
                        created_at=time.time(),
                    )
                )
            await session.commit()

    # ── DB load (restart-resilience) ──────────────────────────────────────────

    async def _load_from_db(self, claim_id: str) -> ClaimRecord | None:
        from sqlalchemy import select

        from app.db.models import ClaimDecisionModel, ClaimModel, FactModel

        async with self._session_factory() as session:
            claim_row = await session.get(ClaimModel, claim_id)
            if claim_row is None:
                return None

            result = await session.execute(
                select(FactModel)
                .where(FactModel.claim_id == claim_id)
                .order_by(FactModel.seq)
            )
            facts = [
                {
                    "seq": f.seq,
                    "key": f.key,
                    "value": f.value,
                    "author": f.author,
                    "confidence": f.confidence,
                    "degraded": f.degraded,
                    "derived_from": f.derived_from or [],
                    "reason": f.reason,
                }
                for f in result.scalars()
            ]

            dec_row = await session.get(ClaimDecisionModel, claim_id)
            decision = None
            if dec_row is not None:
                decision = {
                    "claim_id": claim_id,
                    "status": dec_row.status,
                    "approved_amount": dec_row.approved_amount,
                    "rejection_reasons": dec_row.rejection_reasons or [],
                    "messages": dec_row.messages or [],
                    "notes": dec_row.notes or [],
                    "confidence": dec_row.confidence,
                    "fact_count": dec_row.fact_count,
                }

            return ClaimRecord(
                claim_id=claim_id,
                status=claim_row.status,
                facts=facts,
                decision=decision,
                created_at=claim_row.created_at,
            )
