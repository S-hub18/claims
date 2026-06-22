"""SQLAlchemy async ORM models — claims, facts, claim_decisions.

Uses JSONB on Postgres (Supabase) with a JSON fallback for SQLite (tests/local without DB).
``create_all()`` on startup handles table creation — no Alembic needed.
"""

from __future__ import annotations

import time

from sqlalchemy import Boolean, Column, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON


def _jsonb():
    return JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class ClaimModel(Base):
    __tablename__ = "claims"

    claim_id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="processing")
    created_at = Column(Float, nullable=False, default=time.time)
    updated_at = Column(Float, nullable=True)


class FactModel(Base):
    __tablename__ = "facts"
    __table_args__ = (Index("ix_facts_claim_seq", "claim_id", "seq"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    key = Column(String, nullable=False)
    author = Column(String, nullable=False)
    value = Column(_jsonb(), nullable=True)
    confidence = Column(Float, nullable=True)
    degraded = Column(Boolean, nullable=False, default=False)
    derived_from = Column(_jsonb(), nullable=True)
    reason = Column(String, nullable=True)
    policy_version_id = Column(String, nullable=True)


class ClaimDecisionModel(Base):
    __tablename__ = "claim_decisions"

    claim_id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    approved_amount = Column(Text, nullable=True)
    rejection_reasons = Column(_jsonb(), nullable=True)
    messages = Column(_jsonb(), nullable=True)
    notes = Column(_jsonb(), nullable=True)
    confidence = Column(Float, nullable=True)
    fact_count = Column(Integer, nullable=True)
    created_at = Column(Float, nullable=False, default=time.time)
