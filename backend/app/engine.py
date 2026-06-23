"""The engine entry point: adjudicate one claim end-to-end.

``run_claim`` runs the agent roster to quiescence on the blackboard, then aggregates
the fact-set into a Decision. The roster grows part by part — gate (Part 2), financial
(Part 3), rules (Part 4–5), fraud/degradation (Part 6) — but this seam stays fixed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.aggregator import DecisionAggregator
from app.agents import (
    CrossValidationAgent,
    DocExtractor,
    DocGate,
    DocumentFraudAgent,
    ExclusionAgent,
    FinancialCalculator,
    FinancialReconciler,
    IntakeValidator,
    MemberResolver,
    PerClaimLimitAgent,
    PolicyReasonerAgent,
    PreAuthAgent,
    PrescriptionCorroborationAgent,
    SemanticMapper,
    VelocityFraudAgent,
    WaitingPeriodAgent,
)
from app.blackboard import Agent, Fact, adjudicate
from app.decision import Decision
from app.llm.base import LLMClient
from app.policy import Policy


def build_agents(
    policy: Policy,
    submission: dict[str, Any],
    llm_client: LLMClient | None = None,
    on_post: Callable[[Fact], None] | None = None,
) -> list[Agent]:
    """The agent roster for one claim. One ``DocExtractor`` is created per uploaded
    document. Pass a ``GeminiClient`` for live extraction; omit for offline/eval mode."""
    agents: list[Agent] = [
        MemberResolver(policy),
        IntakeValidator(policy),
        DocGate(policy),
        SemanticMapper(policy),
        ExclusionAgent(policy),
        FinancialReconciler(policy),
        FinancialCalculator(policy),
        WaitingPeriodAgent(policy),
        PreAuthAgent(policy),
        PerClaimLimitAgent(policy),
        VelocityFraudAgent(policy),
        DocumentFraudAgent(policy),
        PrescriptionCorroborationAgent(policy),
        CrossValidationAgent(policy),
        PolicyReasonerAgent(policy, llm_client, on_post=on_post),
    ]
    agents += [
        DocExtractor(d["file_id"], policy, llm_client)
        for d in submission.get("documents", [])
    ]
    return agents


async def run_claim(
    submission: dict[str, Any],
    policy: Policy,
    llm_client: LLMClient | None = None,
    on_post: Callable[[Fact], None] | None = None,
) -> Decision:
    bb = await adjudicate(
        submission, build_agents(policy, submission, llm_client, on_post), on_post=on_post
    )
    return DecisionAggregator(policy).decide(bb)
