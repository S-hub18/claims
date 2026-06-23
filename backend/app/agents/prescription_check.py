"""PrescriptionCorroborationAgent — cross-document check: billed medicines vs prescription.

A bill should not charge for a *specific medicine* that the prescription never ordered.
This is a real fraud/abuse vector (billing for un-prescribed drugs), so when we can
positively identify a billed item as a specific medicine (it carries a dosage or dosage-
form marker, e.g. "Azithromycin 500mg", "Cough Syrup 100ml") and it is not corroborated
by any medicine on the prescription, we raise a MANUAL_REVIEW flag for a human to verify.

Deliberately conservative — a *soft* signal, never a hard exclusion:
  • It only inspects lines it can confidently classify as a specific medicine (dosage/form
    marker). Generic charges — "Consultation Fee", "CBC Test", a lump "Medicines" line —
    are never treated as specific medicines, so legitimate bills that itemise tests or
    fees the prescription doesn't list are not flagged.
  • It does NOT exclude line items or change the approved amount. The money math is
    untouched; only the decision routes to MANUAL_REVIEW so a reviewer can confirm.
  • No prescription, or no identifiable medicine lines → PASS (nothing to corroborate).

This keeps every deterministic outcome intact while adding genuine cross-document
verification to the trace.
"""

from __future__ import annotations

import re

from app.blackboard import Blackboard, Fact, GateGatedAgent
from app.policy import Policy

# Dosage / dosage-form markers that identify a bill line as a *specific* medicine
# (as opposed to a fee, a test, or a generic "Medicines" lump line).
_DOSAGE = re.compile(r"\b\d+\s*(?:mg|mcg|ml|gm|g|iu)\b", re.IGNORECASE)
_FORMS = re.compile(
    r"\b(?:tablet|tab|capsule|cap|syrup|inhaler|injection|inj|ointment|drops|cream|"
    r"lotion|sachet|suspension|gel)\b",
    re.IGNORECASE,
)


def _is_specific_medicine(desc: str) -> bool:
    """True if the bill line names a specific drug (carries a dosage or form marker)."""
    return bool(_DOSAGE.search(desc) or _FORMS.search(desc))


def _tokens(text: str) -> set[str]:
    """Salient (>=4-char) word tokens, lowercased — drug names, not units."""
    cleaned = re.sub(r"\d+\s*(?:mg|mcg|ml|gm|g|iu)\b", " ", text, flags=re.IGNORECASE)
    return {t for t in re.split(r"[^a-z]+", cleaned.lower()) if len(t) >= 4}


def _corroborated(bill_desc: str, prescribed: list[str]) -> bool:
    """True if the billed medicine shares a salient token with any prescribed medicine."""
    bill_tokens = _tokens(bill_desc)
    for med in prescribed:
        if bill_tokens & _tokens(med):
            return True
    return False


class PrescriptionCorroborationAgent(GateGatedAgent):
    name = "prescription_corroboration"
    reads = ["semantic"]
    writes = "verdict.prescription"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        extractions = [f.value for f in bb.all() if f.key.startswith("extraction.")]

        prescribed: list[str] = []
        bill_lines: list[dict] = []
        for ext in extractions:
            content = (ext or {}).get("content") or {}
            dtype = (ext.get("doc_type") or "").upper()
            if dtype == "PRESCRIPTION" or content.get("medicines"):
                prescribed += [str(m) for m in (content.get("medicines") or [])]
            if dtype.endswith("BILL"):
                bill_lines += content.get("line_items") or []

        # Nothing to corroborate against → PASS (e.g. no prescription on this claim).
        if not prescribed:
            return self._pass("No prescription medicines to corroborate against.")

        unsupported = [
            line.get("description", "")
            for line in bill_lines
            if _is_specific_medicine(line.get("description", ""))
            and not _corroborated(line.get("description", ""), prescribed)
        ]

        if unsupported:
            items = "; ".join(unsupported)
            return Fact(
                key=self.writes,
                value={
                    "status": "MANUAL_REVIEW",
                    "reason": "MEDICINE_NOT_PRESCRIBED",
                    "message": (
                        f"The bill charges for medicine(s) not found on the prescription: "
                        f"{items}. Prescribed medicines: {', '.join(prescribed)}. "
                        f"Routing to manual review to confirm these charges are valid."
                    ),
                    "unsupported_items": unsupported,
                    "prescribed": prescribed,
                },
                author=self.name,
                confidence=0.9,
            )

        return self._pass(
            f"All billed medicines corroborated by the prescription "
            f"({len(prescribed)} prescribed)."
        )

    def _pass(self, message: str) -> Fact:
        return Fact(
            key=self.writes,
            value={"status": "PASS", "reason": None, "message": message},
            author=self.name,
            confidence=1.0,
        )
