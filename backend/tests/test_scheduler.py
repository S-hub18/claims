"""Part 0 — prove the blackboard engine fires an agent end-to-end.

Tests are plain sync functions that drive the async scheduler via ``asyncio.run`` so
no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio

from app.agents import EchoAgent
from app.blackboard import Agent, AgentState, Blackboard, Fact, adjudicate


def run(coro):
    return asyncio.run(coro)


def test_echo_agent_fires_and_posts_its_fact():
    submission = {"member_id": "EMP001", "claimed_amount": 1500}
    bb = run(adjudicate(submission, agents=[EchoAgent()]))

    assert bb.has("echo")
    echo = bb.get("echo")
    assert echo.value == {"echo": submission}
    assert echo.author == "echo"
    assert echo.confidence == 1.0


def test_submission_posted_first_and_seq_is_monotonic():
    bb = run(adjudicate({"x": 1}, agents=[EchoAgent()]))
    facts = bb.all()

    assert facts[0].key == "submission"
    assert facts[0].seq == 0
    seqs = [f.seq for f in facts]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))  # unique per claim


def test_derived_from_is_auto_populated_from_reads():
    bb = run(adjudicate({"x": 1}, agents=[EchoAgent()]))
    assert bb.get("echo").derived_from == ("submission",)


def test_failing_agent_yields_degraded_fact_not_an_exception():
    class BoomAgent(Agent):
        name = "boom"
        reads = ["submission"]
        writes = "boom"

        async def _run(self, bb: Blackboard) -> Fact:
            raise RuntimeError("kaboom")

    bb = run(adjudicate({"x": 1}, agents=[BoomAgent()]))

    assert bb.has("boom")
    boom = bb.get("boom")
    assert boom.degraded is True
    assert "kaboom" in boom.value["error"]


def test_skip_state_posts_a_skip_fact_and_never_runs():
    class SkipAgent(Agent):
        name = "skipper"
        reads = ["submission"]
        writes = "skipper"

        def ready(self, bb: Blackboard) -> AgentState:
            return AgentState.SKIP

        def skip_reason(self, bb: Blackboard) -> str:
            return "PROVABLY_PASS"

        async def _run(self, bb: Blackboard) -> Fact:
            raise AssertionError("a skipped agent must not run")

    bb = run(adjudicate({"x": 1}, agents=[SkipAgent()]))

    assert bb.has("skipped.skipper")
    assert bb.get("skipped.skipper").reason == "PROVABLY_PASS"


def test_determinism_same_inputs_same_factset():
    runs = [run(adjudicate({"x": 1}, agents=[EchoAgent()])) for _ in range(20)]
    keysets = [tuple(sorted(bb.keys())) for bb in runs]
    assert len(set(keysets)) == 1  # identical fact-set every run
