"""The final adjudication result — what the aggregator produces and the API returns."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.blackboard import Fact


@dataclass
class Decision:
    """One claim's outcome. ``status`` is the §5 verdict; the rest is the explanation.

    ``trace`` is the full ordered fact-set — the replayable record of how the engine
    reached this status (Observability, ARCHITECTURE §6.7).
    """

    status: str  # BLOCKED | REJECTED | MANUAL_REVIEW | PARTIAL | APPROVED
    approved_amount: Decimal | None = None
    rejection_reasons: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confidence: float | None = None
    trace: list[Fact] = field(default_factory=list)
