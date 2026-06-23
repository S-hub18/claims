"""DocGate — the collect-all, report-once document verification gate (PRD §4.3).

This is competitive edge #1. A naive system rejects on the first document problem it
hits; this one collects **every** problem across all documents and reports them in a
single ``gate`` fact, so the member fixes everything in one round-trip rather than N.

Checks (all run, all accumulate):
  1. readability      — any unreadable document → ask to re-upload *that* document
  2. required types   — every required doc type for the category is present
  3. patient match    — every named document belongs to the member or a covered dependent

Dependency rule: an unreadable document is a *readability* problem, not a *missing*
one — we still know its claimed type, so it counts as present for check 2, and its
(unreadable) patient name is skipped for check 3. The gate always posts a ``gate``
fact — blocked or not — so downstream ``GateGatedAgent``s can decide deterministically.
"""

from __future__ import annotations

from app.blackboard import Agent, AgentState, Blackboard, Fact
from app.policy import Policy


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


class DocGate(Agent):
    name = "doc_gate"
    reads = ["submission", "member"]
    writes = "gate"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    def ready(self, bb: Blackboard) -> AgentState:
        """Fire once the member is resolved and *every* document has been extracted."""
        if not (bb.has("submission") and bb.has("member")):
            return AgentState.WAIT
        file_ids = [d.get("file_id") for d in bb.get("submission").value.get("documents", [])]
        if not file_ids or all(bb.has(f"extraction.{fid}") for fid in file_ids):
            return AgentState.READY
        return AgentState.WAIT

    async def _run(self, bb: Blackboard) -> Fact:
        submission = bb.get("submission").value
        category = submission.get("claim_category", "")
        docs = [
            bb.get(f"extraction.{d['file_id']}").value for d in submission.get("documents", [])
        ]
        issues: list[str] = []

        # 1. Readability.
        for doc in docs:
            # A system extraction failure (quota/network) is not a readability verdict —
            # the aggregator surfaces it as PROCESSING_ERROR. Don't tell the member to
            # re-upload a document that was never actually assessed.
            if doc.get("system_error"):
                continue
            if not doc.get("readable"):
                label = doc.get("doc_type") or "document"
                ref = doc.get("file_name") or doc.get("file_id")
                issues.append(
                    f"The {label} ({ref}) could not be read. "
                    f"Please re-upload a clear photo of your {label}."
                )

        # 1b. Usable-bill check. A bill the model called "readable" but from which NO
        # charges and NO total could be extracted (e.g. a blurred photo) is useless for
        # adjudication — we cannot verify the claimed amount against it. Treat it as a
        # readability failure and ask for a re-upload, rather than silently letting the
        # financial calculator fall back to the member's self-declared amount and approve
        # an unverifiable claim (PRD §4.3; assignment TC002).
        for doc in docs:
            if doc.get("system_error"):
                continue
            dtype = (doc.get("doc_type") or "").upper()
            if not dtype.endswith("BILL"):
                continue
            content = doc.get("content") or {}
            has_amounts = bool(content.get("line_items")) or content.get("total") is not None
            if doc.get("readable") and not has_amounts:
                ref = doc.get("file_name") or doc.get("file_id")
                issues.append(
                    f"The {dtype} ({ref}) could not be read clearly — no charges or bill "
                    f"total could be extracted. Please re-upload a clearer photo of the bill."
                )

        # 2. Required document types (claimed type counts as present even if unreadable).
        present = {doc.get("doc_type") for doc in docs}
        uploaded = [doc.get("doc_type") for doc in docs]
        required = self.policy.required_documents(category)
        for req in required:
            if req not in present:
                uploaded_str = ", ".join(uploaded) if uploaded else "none"
                issues.append(
                    f"Your {category} claim requires a {req}. The document(s) you "
                    f"uploaded were: {uploaded_str}. Please upload a {req}."
                )

        # 3. Patient match — every readable, named document must (a) name the SAME single
        # patient and (b) that patient must be the member or a covered dependent. A claim
        # whose prescription and bill name different people is a document-integrity failure
        # (cross-document mismatch), even if both names happen to be covered.
        member = bb.get("member").value
        covered: set[str] = set()
        member_name = None
        if member.get("found"):
            member_name = member["record"].get("name")
            covered.add(_norm(member_name))
            for dep in member.get("dependents", []):
                covered.add(_norm(dep.get("name")))
        named = [
            (doc.get("doc_type"), doc.get("patient_name"))
            for doc in docs
            if doc.get("readable") and doc.get("patient_name")
        ]
        distinct = {_norm(nm) for _, nm in named}
        if len(distinct) > 1:
            roster = "; ".join(f"the {dt} is for '{nm}'" for dt, nm in named)
            issues.append(
                f"The documents name different patients: {roster}. All documents for one "
                f"claim must be for the same person (the member or a covered dependent)."
            )
        elif distinct and covered and not (distinct <= covered):
            nm = next(nm for _, nm in named)
            issues.append(
                f"The documents are for '{nm}', who is not the member '{member_name}' or a "
                f"covered dependent."
            )

        return Fact(
            key="gate",
            value={
                "blocked": bool(issues),
                "issues": issues,
                "present_types": sorted(t for t in present if t),
                "required": required,
            },
            author=self.name,
            confidence=1.0,
        )
