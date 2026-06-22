"""ExclusionAgent — coverage determination: whole-claim and line-item exclusions.

Posts one ``coverage`` fact that everything downstream (the calculator, the per-claim
limit, the aggregator) reads. Two layers, both policy-driven:

  • whole-claim — the diagnosis/treatment matches a general policy exclusion
    (``exclusions.conditions``) → the whole claim is rejected (TC012, obesity/bariatric).
  • line-item  — an individual bill line matches the category's excluded procedures/items
    (``opd_categories[cat].excluded_*``) → that line is disallowed, the rest proceeds
    (TC006, teeth whitening excluded, root canal kept → PARTIAL).

The exclusion *terms* come from policy; only the matching logic is code (no hardcoded
condition names). ``covered_amount`` is the post-exclusion sum the money math uses.
"""

from __future__ import annotations

from decimal import Decimal

from app.blackboard import Blackboard, Fact, GateGatedAgent
from app.policy import Policy

# Generic tokens that would over-match if treated as exclusion keywords. Removing them
# keeps "Obesity and weight loss programs" matching on "obesity", not on "programs".
_STOPWORDS = {
    "and",
    "or",
    "non",
    "the",
    "treatment",
    "treatments",
    "program",
    "programs",
    "procedure",
    "procedures",
    "surgery",
    "surgical",
    "related",
    "other",
    "weight",
    "loss",
    "hazard",
    "health",  # from "Health supplements"; "supplements" still carries that exclusion
}


def _d(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _keywords(phrases: list[str]) -> set[str]:
    """Salient (>=5-char, non-stopword) tokens from policy exclusion phrases."""
    keywords: set[str] = set()
    for phrase in phrases:
        cleaned = phrase.replace("(", " ").replace(")", " ").replace("-", " ")
        for token in cleaned.split():
            tok = token.strip().lower()
            if len(tok) >= 5 and tok not in _STOPWORDS:
                keywords.add(tok)
    return keywords


class ExclusionAgent(GateGatedAgent):
    name = "exclusion"
    reads = ["semantic"]
    writes = "coverage"

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    async def _run(self, bb: Blackboard) -> Fact:
        semantic = bb.get("semantic").value
        category = semantic.get("category", "")
        lines = [dict(line) for line in semantic.get("lines", [])]

        # Text the whole-claim check scans: diagnosis, treatment, line descriptions.
        text_parts: list[str] = []
        for fact in bb.all():
            if fact.key.startswith("extraction."):
                content = fact.value.get("content") or {}
                for key in ("diagnosis", "treatment"):
                    if content.get(key):
                        text_parts.append(str(content[key]))
        text_parts += [line.get("description", "") for line in lines]
        text = " ".join(text_parts).lower()

        excluded_keywords = _keywords(self.policy.get("exclusions.conditions", []))
        matched = sorted(k for k in excluded_keywords if k in text)
        whole_claim_excluded = bool(matched)

        cat = self.policy.category(category)
        category_excluded = cat.get("excluded_procedures") or cat.get("excluded_items") or []

        message: str | None = None
        if whole_claim_excluded:
            for line in lines:
                line["excluded"] = True
                line["reason"] = "EXCLUDED_CONDITION"
            message = (
                f"This claim is for an excluded condition (matched policy exclusion "
                f"term: {', '.join(matched)}). Such treatments are not covered."
            )
        else:
            for line in lines:
                desc = line.get("description", "").lower()
                hit = next(
                    (e for e in category_excluded if e.lower() in desc or desc in e.lower()),
                    None,
                )
                if hit:
                    line["excluded"] = True
                    line["reason"] = f"{hit} is excluded under the {category} policy"

        covered = [line for line in lines if not line.get("excluded")]
        excluded = [line for line in lines if line.get("excluded")]
        covered_amount = sum((_d(line["amount"]) for line in covered), Decimal(0))

        if excluded and not whole_claim_excluded:
            approved_str = (
                "; ".join(f"{line['description']} (₹{line['amount']})" for line in covered)
                or "none"
            )
            excluded_str = "; ".join(
                f"{line['description']} (₹{line['amount']}) — {line['reason']}" for line in excluded
            )
            message = (
                f"Approved line items: {approved_str}. Excluded line items: {excluded_str}."
            )

        return Fact(
            key="coverage",
            value={
                "category": category,
                "lines": lines,
                "covered_amount": str(covered_amount),
                "covered_count": len(covered),
                "excluded_count": len(excluded),
                "whole_claim_excluded": whole_claim_excluded,
                "matched_terms": matched,
                "message": message,
            },
            author=self.name,
            confidence=1.0,
        )
