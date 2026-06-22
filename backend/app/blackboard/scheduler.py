"""The scheduler — fires agents the instant their inputs exist. ~50 lines.

No phases, no barriers: a single loop polls pending agents, launches the READY ones
concurrently, and posts each result as it lands. B-static — each agent fires at most
once. A wall-clock deadline drains any stragglers as degraded facts. See
ARCHITECTURE.md §7.3.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from typing import Any

from .core import Agent, AgentState, Blackboard, Fact


async def adjudicate(
    submission: Any,
    agents: Iterable[Agent],
    timeout_s: float = 120.0,
    on_post: Callable[[Fact], None] | None = None,
) -> Blackboard:
    """Run a claim to quiescence and return the populated blackboard.

    ``on_post`` is an optional hook invoked for every posted fact — the seam where
    SSE emission and DB persistence attach in later parts. In-memory only for now.
    """
    bb = Blackboard()
    _post(bb, Fact(key="submission", value=submission, author="intake"), None, on_post)

    pending: set[Agent] = set(agents)
    running: dict[Agent, asyncio.Task[Fact]] = {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    while pending or running:
        # Fire every agent whose inputs are now satisfied; prune the provably-skippable.
        for agent in list(pending):
            state = agent.ready(bb)
            if state is AgentState.SKIP:
                pending.discard(agent)
                reason = agent.skip_reason(bb)
                _post(
                    bb,
                    Fact(
                        key=f"skipped.{agent.name}",
                        value={"reason": reason},
                        author=agent.name,
                        reason=reason,
                    ),
                    agent,
                    on_post,
                )
            elif state is AgentState.READY:
                pending.discard(agent)
                running[agent] = asyncio.create_task(agent.run(bb))

        if not running:
            break  # quiescent: nothing running and nothing newly ready

        remaining = deadline - loop.time()
        if remaining <= 0:  # wall-clock timeout — drain the remainder as degraded
            for agent in list(pending):
                _post(
                    bb,
                    Fact(
                        key=f"skipped.{agent.name}",
                        value={"reason": "TIMEOUT"},
                        author=agent.name,
                        degraded=True,
                        reason="TIMEOUT",
                    ),
                    agent,
                    on_post,
                )
            pending.clear()
            for task in running.values():
                task.cancel()
            break

        done, _ = await asyncio.wait(
            running.values(), return_when=asyncio.FIRST_COMPLETED, timeout=remaining
        )
        for task in done:
            agent = next(a for a, t in running.items() if t is task)
            del running[agent]
            _post(bb, task.result(), agent, on_post)

    return bb


def _post(
    bb: Blackboard, fact: Fact, agent: Agent | None, on_post: Callable[[Fact], None] | None
) -> Fact:
    stored = bb.post(fact, agent)
    if on_post is not None:
        on_post(stored)
    return stored
