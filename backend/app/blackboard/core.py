"""Core blackboard primitives: the Fact, the fact store, and the agent contract.

The blackboard is an append-only store of immutable Facts. Agents declare the fact
keys they read; the scheduler (scheduler.py) fires each agent the instant its reads
exist. B-static: every agent fires at most once. See ARCHITECTURE.md §7.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any


@dataclass(frozen=True, slots=True)
class Fact:
    """A single immutable assertion on the blackboard.

    Mirrors the SSE event schema (ARCHITECTURE.md §6.7). ``seq`` and ``derived_from``
    are assigned by ``Blackboard.post()``; agents leave them at their defaults.
    """

    key: str
    value: Any
    author: str
    seq: int = -1  # assigned by Blackboard.post()
    confidence: float | None = None
    degraded: bool = False
    derived_from: tuple[str, ...] = ()
    policy_version_id: str | None = None
    # skipped facts carry a reason: PROVABLY_PASS | GATE_BLOCKED | GUARD_FIRED | TIMEOUT
    reason: str | None = None


class AgentState(Enum):
    """Tri-state readiness returned by ``Agent.ready()`` (ARCHITECTURE.md §7.3)."""

    WAIT = "wait"  # preconditions not yet on the board — keep polling
    READY = "ready"  # all inputs exist — fire now
    SKIP = "skip"  # will never be needed — post a skip fact and prune


class Blackboard:
    """Append-only fact store with a per-claim monotonic sequence counter."""

    def __init__(self) -> None:
        self._facts: list[Fact] = []
        self._by_key: dict[str, Fact] = {}
        self._seq = 0

    def post(self, fact: Fact, agent: Agent | None = None) -> Fact:
        """Assign ``seq`` + lineage, store, and return the stored fact.

        ``derived_from`` is auto-populated from the posting agent's ``reads`` so
        agents never bookkeep lineage by hand (ARCHITECTURE.md §7.3).
        """
        derived = tuple(agent.reads) if agent is not None else fact.derived_from
        stored = replace(fact, seq=self._seq, derived_from=derived)
        self._seq += 1
        self._facts.append(stored)
        self._by_key[stored.key] = stored
        return stored

    def has(self, key: str) -> bool:
        return key in self._by_key

    def has_prefix(self, prefix: str) -> bool:
        """True if any posted key starts with ``prefix`` (e.g. ``extraction.``)."""
        return any(k.startswith(prefix) for k in self._by_key)

    def get(self, key: str) -> Fact | None:
        return self._by_key.get(key)

    def all(self) -> list[Fact]:
        """Every fact in canonical order (by ``seq``) — the replayable trace."""
        return sorted(self._facts, key=lambda f: f.seq)

    def keys(self) -> list[str]:
        return list(self._by_key)

    def skipped(self) -> dict[str, str]:
        """Agent-name → skip reason, read from posted ``skipped.*`` facts.

        The trace's record of who never ran and why (PROVABLY_PASS, GATE_BLOCKED,
        TIMEOUT) — surfaced in the decision output for observability.
        """
        return {
            f.key.removeprefix("skipped."): (f.reason or "")
            for f in self._facts
            if f.key.startswith("skipped.")
        }


class Agent:
    """Base agent. Subclasses set ``name``, ``reads``, ``writes`` and implement ``_run``.

    ``run()`` is the safe entry point the scheduler calls — it never raises; on any
    failure it returns a degraded fact, so a component failure is recorded rather than
    fatal (ARCHITECTURE.md principle 6).
    """

    name: str = "agent"
    reads: list[str] = []
    writes: str = ""

    def ready(self, bb: Blackboard) -> AgentState:
        """Default readiness: fire once every declared read exists."""
        return AgentState.READY if all(bb.has(k) for k in self.reads) else AgentState.WAIT

    def skip_reason(self, bb: Blackboard) -> str:
        return "PROVABLY_PASS"

    async def run(self, bb: Blackboard) -> Fact:
        try:
            return await self._run(bb)
        except Exception as exc:  # never raises — degraded fact instead of a crash
            return Fact(
                key=self.writes or f"{self.name}.error",
                value={"error": str(exc)},
                author=self.name,
                degraded=True,
            )

    async def _run(self, bb: Blackboard) -> Fact:
        raise NotImplementedError


class GateGatedAgent(Agent):
    """An agent that must not run once the document gate has BLOCKED the claim.

    Every downstream rule/financial agent (Part 2 on) inherits this. The gate always
    posts a ``gate`` fact — blocked or not — so this is deterministic: WAIT until the
    gate has decided, SKIP (reason GATE_BLOCKED) if it blocked, else fall back to the
    normal reads check (PRD §4.3; ARCHITECTURE §7.3).
    """

    def ready(self, bb: Blackboard) -> AgentState:
        if not bb.has("gate"):
            return AgentState.WAIT
        if bb.get("gate").value.get("blocked"):
            return AgentState.SKIP
        return super().ready(bb)

    def skip_reason(self, bb: Blackboard) -> str:
        return "GATE_BLOCKED"
