"""The policy loader — policy is *data*, not code.

Every threshold the engine uses (limits, co-pays, waiting periods, document
requirements, fraud thresholds, the member roster) is resolved from
``policy_terms.json`` at runtime. No policy literal is embedded in the engine
(PRD §2.1, §6). Swap the JSON → behaviour changes with zero code change.

Access by dotted path via :meth:`Policy.get`, or via the named convenience
accessors which reference the *key* a value lives at, never the literal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MISSING = object()


class Policy:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def from_file(cls, path: str | Path) -> Policy:
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    @property
    def version_id(self) -> str:
        return str(self._data.get("policy_id", "unknown"))

    def get(self, path: str, default: Any = _MISSING) -> Any:
        """Resolve a dotted path (e.g. ``coverage.per_claim_limit``).

        Raises ``KeyError`` for a missing path unless ``default`` is given — so a
        typo'd policy key fails loud rather than silently reading ``None``.
        """
        node: Any = self._data
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                if default is _MISSING:
                    raise KeyError(f"policy path not found: {path!r}")
                return default
        return node

    # --- named accessors -------------------------------------------------
    def category(self, claim_category: str) -> dict[str, Any]:
        """The ``opd_categories`` block for a claim category (case-normalised)."""
        return self.get(f"opd_categories.{claim_category.lower()}")

    def required_documents(self, claim_category: str) -> list[str]:
        return self.get(f"document_requirements.{claim_category.upper()}.required")

    def optional_documents(self, claim_category: str) -> list[str]:
        return self.get(f"document_requirements.{claim_category.upper()}.optional", [])

    def per_claim_limit(self) -> Any:
        return self.get("coverage.per_claim_limit")

    def waiting_period_days(self, condition: str) -> Any:
        """Waiting-period days for a specific condition, or ``None`` if unlisted."""
        return self.get(f"waiting_periods.specific_conditions.{condition}", None)

    def network_hospitals(self) -> list[str]:
        return self.get("network_hospitals", [])

    def is_network_hospital(self, name: str | None) -> bool:
        if not name:
            return False
        n = name.strip().lower()
        return any(
            n == h.strip().lower()          # exact: "Apollo Hospitals" == "Apollo Hospitals"
            or n in h.strip().lower()       # partial: "apollo hospital" in "apollo hospitals"
            or h.strip().lower() in n       # reverse: "apollo hospitals" in "apollo hospitals delhi"
            for h in self.network_hospitals()
        )

    def min_claim_amount(self) -> Any:
        return self.get("submission_rules.minimum_claim_amount")

    def fraud(self, key: str) -> Any:
        return self.get(f"fraud_thresholds.{key}")

    def members(self) -> list[dict[str, Any]]:
        return self.get("members", [])

    def member(self, member_id: str | None) -> dict[str, Any] | None:
        if not member_id:
            return None
        for rec in self.members():
            if rec.get("member_id") == member_id:
                return rec
        return None
