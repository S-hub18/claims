"""Decision aggregation — reduces a quiescent blackboard to one Decision (PRD §5).

The aggregator runs *after* the scheduler reaches quiescence, not as a blackboard
agent, so it sees the complete fact-set and never has to guess whether everyone has
fired. Parts 2–6 add the agents that post the facts this ladder reads; the ladder
itself is the stable spine.
"""

from __future__ import annotations

from decimal import Decimal

from app.blackboard import Blackboard
from app.decision import Decision
from app.policy import Policy

# Reason precedence is decision *logic*, not policy data (PRD §5): it orders which
# rejection reason is primary when several apply. These are ranks, not thresholds —
# they never come from policy_terms.json. (TC012: EXCLUDED outranks PER_CLAIM.)
REASON_RANK = {
    "EXCLUDED_CONDITION": 4,
    "WAITING_PERIOD": 3,
    "PRE_AUTH_MISSING": 2,
    "PER_CLAIM_EXCEEDED": 1,
}

# Confidence model constants (PRD §4.13). Tuned so a clean approval clears the TC004
# (>0.85) and TC012 (>0.90) bars while each component failure visibly lowers it (TC011).
_BASE = Decimal("0.95")
_DEGRADATION_PENALTY = Decimal("0.25")


class DecisionAggregator:
    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def _confidence(self, bb: Blackboard) -> float:
        """Explainable, component-based confidence (PRD §4.13).

        ``base × min(extraction_quality, rule_certainty)`` minus a penalty per failed
        component, so a degraded run is measurably less confident than a clean one.
        """
        facts = bb.all()
        extraction = [
            f.confidence for f in facts if f.key.startswith("extraction.") and f.confidence is not None
        ]
        rules = [
            f.confidence for f in facts if f.key.startswith("verdict.") and f.confidence is not None
        ]
        extraction_quality = (
            sum(Decimal(str(c)) for c in extraction) / len(extraction) if extraction else Decimal(1)
        )
        rule_certainty = sum(Decimal(str(c)) for c in rules) / len(rules) if rules else Decimal(1)
        degraded = sum(1 for f in facts if f.degraded)
        raw = _BASE * min(extraction_quality, rule_certainty) - _DEGRADATION_PENALTY * degraded
        return float(round(max(Decimal(0), min(Decimal(1), raw)), 4))

    def decide(self, bb: Blackboard) -> Decision:
        facts = bb.all()
        confidence = self._confidence(bb)

        # Graceful degradation overlay (PRD §4.14): if a non-critical component failed
        # (posted a degraded fact), the status stands but we make the failure visible and
        # recommend manual review. Confidence is already lowered in _confidence().
        degraded = sorted({f.author for f in facts if f.degraded})
        overlay = (
            [
                f"⚠ A component ({', '.join(degraded)}) failed during processing and was "
                "skipped. The decision was made on the remaining checks; manual review is "
                "recommended due to incomplete processing."
            ]
            if degraded
            else []
        )

        # 1. Document problem present → BLOCKED (the gate posts in Part 2).
        gate = bb.get("gate")
        if gate is not None and gate.value.get("blocked"):
            return Decision(
                status="BLOCKED",
                messages=list(gate.value.get("issues", [])),
                confidence=confidence,
                trace=facts,
            )

        verdicts = [f for f in facts if f.key.startswith("verdict.")]
        coverage = bb.get("coverage")

        # 2. Any definitive violation → REJECTED, reasons ranked (Part 4). Sources: the
        # rule agents' ``verdict.*`` rejects plus a whole-claim exclusion from coverage.
        rejects: list[tuple[str, str]] = [  # (reason, message)
            (f.value["reason"], f.value.get("message", ""))
            for f in verdicts
            if f.value.get("status") == "REJECTED" and f.value.get("reason") in REASON_RANK
        ]
        if coverage is not None and coverage.value.get("whole_claim_excluded"):
            rejects.append(("EXCLUDED_CONDITION", coverage.value.get("message", "")))
        if rejects:
            rejects.sort(key=lambda r: REASON_RANK[r[0]], reverse=True)
            return Decision(
                status="REJECTED",
                rejection_reasons=[reason for reason, _ in rejects],
                messages=[msg for _, msg in rejects if msg],
                confidence=confidence,
                trace=facts,
            )

        # Intake hard-fail (e.g. below the minimum claim amount) — also a REJECT,
        # outside the §5 rank ladder.
        intake = bb.get("verdict.intake")
        if intake is not None and intake.value.get("status") == "REJECTED":
            return Decision(
                status="REJECTED",
                rejection_reasons=[intake.value.get("reason", "INVALID_CLAIM")],
                messages=[intake.value.get("message", "")],
                confidence=confidence,
                trace=facts,
            )

        fin = bb.get("financial_breakdown")
        approved_amount = Decimal(str(fin.value["approved_amount"])) if fin is not None else None
        fin_notes = [fin.value["note"]] if fin is not None and fin.value.get("note") else []

        # 3. Fraud flag / high-value / low-confidence → MANUAL_REVIEW (Part 6).
        manual = [f for f in verdicts if f.value.get("status") == "MANUAL_REVIEW"]
        if manual:
            return Decision(
                status="MANUAL_REVIEW",
                approved_amount=approved_amount,
                messages=[f.value["message"] for f in manual if f.value.get("message")],
                notes=fin_notes + overlay,
                confidence=confidence,
                trace=facts,
            )

        # 4/5. Line-item exclusions → REJECTED (all covered lines excluded) or PARTIAL
        # (some excluded, ≥1 approved). Whole-claim exclusion was handled in step 2.
        if coverage is not None and not coverage.value.get("whole_claim_excluded"):
            covered_count = coverage.value.get("covered_count", 1)
            excluded_count = coverage.value.get("excluded_count", 0)
            if excluded_count and covered_count == 0:
                return Decision(
                    status="REJECTED",
                    rejection_reasons=["EXCLUDED_CONDITION"],
                    messages=[coverage.value.get("message", "")],
                    confidence=confidence,
                    trace=facts,
                )
            if excluded_count and covered_count:
                return Decision(
                    status="PARTIAL",
                    approved_amount=approved_amount,
                    messages=[coverage.value.get("message", "")],
                    notes=fin_notes + overlay,
                    confidence=confidence,
                    trace=facts,
                )

        # 6. Otherwise → APPROVED.
        return Decision(
            status="APPROVED",
            approved_amount=approved_amount,
            notes=fin_notes + overlay,
            confidence=confidence,
            trace=facts,
        )
