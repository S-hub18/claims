"""Fraud agents (PRD §4.9). Fraud produces a FLAG, never an auto-reject, and is applied
only at aggregation (a definitive REJECTED always outranks a FLAG).

  VelocityFraudAgent  — Track 1, fires at intake (NOT gate-gated, needs no documents):
                        same-day / monthly velocity + high-value (TC009 → MANUAL_REVIEW).
  DocumentFraudAgent  — Track 2, runs after extraction (gate-gated). Non-critical: if it
                        fails, the pipeline degrades gracefully rather than crashing
                        (TC011, via ``simulate_component_failure``).

Velocity reads the claim's *inline* ``claims_history``, which is per-case isolated by
construction — re-running the eval cannot inflate counts (the ledger-leak trap, PRD
§4.9). The persistent cross-claim ledger arrives with the DB in Part 8.
"""

from __future__ import annotations

from decimal import Decimal

from app.blackboard import Agent, Blackboard, Fact, GateGatedAgent
from app.policy import Policy


def _d(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


class VelocityFraudAgent(Agent):
    name = "velocity_fraud"
    reads = ["submission"]
    writes = "verdict.fraud"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        treated = submission.get("treatment_date")
        history = submission.get("claims_history") or []
        same_day_limit = self.policy.fraud("same_day_claims_limit")
        monthly_limit = self.policy.fraud("monthly_claims_limit")
        high_value = _d(self.policy.fraud("auto_manual_review_above"))
        amount = _d(submission.get("claimed_amount"))

        signals: list[str] = []
        same_day = sum(1 for c in history if c.get("date") == treated) + 1
        if same_day > same_day_limit:
            signals.append(
                f"{same_day} claims on the same day ({treated}) — exceeds the limit of "
                f"{same_day_limit}"
            )
        month = str(treated or "")[:7]
        monthly = sum(1 for c in history if str(c.get("date") or "")[:7] == month) + 1
        if monthly > monthly_limit:
            signals.append(
                f"{monthly} claims in {month} — exceeds the monthly limit of {monthly_limit}"
            )
        if amount >= high_value:
            signals.append(
                f"claimed amount ₹{amount} is at/above the ₹{high_value} high-value "
                f"review threshold"
            )

        if signals:
            return Fact(
                key=self.writes,
                value={
                    "status": "MANUAL_REVIEW",
                    "reason": "FRAUD_FLAG",
                    "message": "Routed to manual review for unusual activity: "
                    + "; ".join(signals)
                    + ".",
                    "signals": signals,
                },
                author=self.name,
                confidence=1.0,
            )
        return Fact(key=self.writes, value={"status": "PASS"}, author=self.name, confidence=1.0)


class DocumentFraudAgent(GateGatedAgent):
    name = "document_fraud"
    reads = ["submission"]
    writes = "verdict.docfraud"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        if submission.get("simulate_component_failure"):
            # Agent.run() catches this and posts a *degraded* fact — the pipeline
            # continues, confidence drops, and the aggregator recommends manual review.
            raise RuntimeError("document fraud scorer unavailable (simulated component failure)")
        # Offline: no document anomaly signals are injected → PASS. Real perceptual
        # signals (altered amounts, duplicate stamps, line-sum mismatch) arrive from
        # vision extraction in Part 7.
        return Fact(key=self.writes, value={"status": "PASS"}, author=self.name, confidence=1.0)
