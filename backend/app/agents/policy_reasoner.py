"""PolicyReasonerAgent — LangGraph-powered policy reasoning layer.

Fires after ExclusionAgent posts the keyword-based `coverage` fact. Internally runs a
LangGraph StateGraph where Gemini uses tool calling (verify_exclusion, lookup_policy_clause)
to verify the keyword verdict against clinical context.

Three terminal branches:
  CONFIRM  — LangGraph agrees with keyword result → keyword coverage stands, no new fact
  OVERRIDE — LangGraph finds keyword was wrong → posts `coverage.revised`
  ESCALATE — ambiguous after MAX_ITERS passes → posts `flag.ambiguity` → MANUAL_REVIEW

The preliminary_decision fact is posted at the start of _run() so the client sees a fast
keyword-based answer (~0.6s) while LangGraph reasons in the background over SSE.
"""

from __future__ import annotations

from decimal import Decimal
from operator import add
from typing import Annotated, Any, Callable, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.blackboard import Blackboard, Fact, GateGatedAgent
from app.policy import Policy

MAX_ITERS = 3
CONFIDENCE_DECIDE = 0.75


class ReasonerState(TypedDict):
    # ── inputs (set once by load_context) ────────────────────────────────
    category: str
    keyword_excluded: bool
    matched_terms: list[str]
    clinical_text: str
    lines: list[dict]
    # ── working state ─────────────────────────────────────────────────────
    iteration: int
    ambiguous: bool
    tool_calls: Annotated[list[dict], add]
    findings: Annotated[list[str], add]
    confidence: float
    # ── output ───────────────────────────────────────────────────────────
    verdict: Literal["CONFIRM", "OVERRIDE", "ESCALATE", ""]
    revised_excluded: bool | None
    revised_lines: list[dict] | None
    rationale: str
    # ── infra (not LLM-visible) ───────────────────────────────────────────
    emit: Any    # Callable[[str, dict], None] — posts policy_reasoning.step facts
    policy: Any  # Policy
    llm: Any     # GeminiClient | None


# ── Nodes ──────────────────────────────────────────────────────────────────────


def _load_context(state: ReasonerState) -> dict:
    state["emit"]("Starting policy reasoning", {
        "phase": "load_context",
        "category": state["category"],
        "keyword_excluded": state["keyword_excluded"],
        "matched_terms": state["matched_terms"],
    })
    return {
        "iteration": 0,
        "ambiguous": False,
        "tool_calls": [],
        "findings": [f"Policy reasoning started for category: {state['category']}"],
        "confidence": 0.0,
        "verdict": "",
        "revised_excluded": None,
        "revised_lines": None,
        "rationale": "",
    }


async def _identify_ambiguity(state: ReasonerState) -> dict:
    emit = state["emit"]

    if not state["keyword_excluded"] and not state["matched_terms"]:
        emit("No exclusion keywords matched — claim is clearly covered", {
            "phase": "identify_ambiguity", "ambiguous": False,
        })
        return {
            "ambiguous": False,
            "confidence": 0.95,
            "findings": ["No exclusion keywords matched; claim appears clearly covered."],
        }

    llm = state["llm"]
    if llm is None or not hasattr(llm, "reason_simple"):
        return {
            "ambiguous": True,
            "confidence": 0.0,
            "findings": ["LLM unavailable; deferring to full verification."],
        }

    schema = {
        "type": "object",
        "properties": {
            "ambiguous": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "required": ["ambiguous", "reason"],
    }
    prompt = (
        f"Clinical text: {state['clinical_text'][:500]}\n"
        f"Matched exclusion terms: {state['matched_terms']}\n"
        f"Category: {state['category']}\n\n"
        "Is coverage genuinely ambiguous? The matched terms might be incidental comorbidities "
        "or billing aliases rather than the actual billed procedure.\n"
        'Respond with JSON: {"ambiguous": bool, "reason": "one sentence"}'
    )
    try:
        result = await llm.reason_simple(prompt, schema)
        ambiguous: bool = result.get("ambiguous", True)
        reason: str = result.get("reason", "")
        emit(
            f"Ambiguity check: {'ambiguous' if ambiguous else 'clear'} — {reason}",
            {"phase": "identify_ambiguity", "ambiguous": ambiguous},
        )
        return {
            "ambiguous": ambiguous,
            "confidence": 0.6 if ambiguous else 0.9,
            "findings": [f"Ambiguity assessment: {reason}"],
        }
    except Exception as exc:
        emit(f"Ambiguity check error; proceeding with full verification: {exc}",
             {"phase": "identify_ambiguity", "error": str(exc)})
        return {
            "ambiguous": True,
            "confidence": 0.3,
            "findings": [f"Ambiguity check failed ({exc}); defaulting to full verification."],
        }


async def _verify_exclusions(state: ReasonerState) -> dict:
    emit = state["emit"]
    llm = state["llm"]
    policy = state["policy"]
    iteration = state["iteration"] + 1

    emit(f"Verification pass {iteration}: calling policy tools", {
        "phase": "verify_exclusions", "iteration": iteration,
    })

    if llm is None or not hasattr(llm, "reason"):
        return {
            "iteration": iteration,
            "confidence": 0.0,
            "findings": ["LLM unavailable."],
        }

    tool_declarations = [
        {
            "name": "verify_exclusion",
            "description": (
                "Check whether a medical term is genuinely an excluded condition given "
                "the clinical context, or just an incidental comorbidity or billing alias. "
                "Returns matched policy exclusion phrases so the model can judge intent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "The matched exclusion term"},
                    "clinical_context": {"type": "string", "description": "Relevant clinical text"},
                },
                "required": ["term", "clinical_context"],
            },
        },
        {
            "name": "lookup_policy_clause",
            "description": (
                "Return the full policy clause, excluded procedures, and excluded items "
                "for a given claim category."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "The claim category"},
                },
                "required": ["category"],
            },
        },
    ]

    def _exec_verify_exclusion(args: dict) -> dict:
        term = args.get("term", "")
        exclusion_phrases = policy.get("exclusions.conditions", [])
        matched = [p for p in exclusion_phrases
                   if term.lower() in p.lower() or p.lower() in term.lower()]
        emit(
            f"Tool verify_exclusion('{term}'): matched={matched[:2]}",
            {"phase": "verify_exclusions", "iteration": iteration,
             "tool": "verify_exclusion", "term": term, "matched_phrases": matched},
        )
        return {
            "term": term,
            "policy_exclusion_phrases": matched,
            "matched": bool(matched),
            "clinical_context_provided": args.get("clinical_context", "")[:200],
        }

    def _exec_lookup_policy_clause(args: dict) -> dict:
        cat_name = args.get("category", state["category"])
        cat = policy.get(f"opd_categories.{cat_name.lower()}", {})
        result = {
            "category": cat_name,
            "covered": cat.get("covered", True),
            "excluded_procedures": cat.get("excluded_procedures") or [],
            "excluded_items": cat.get("excluded_items") or [],
        }
        emit(
            f"Tool lookup_policy_clause('{cat_name}'): covered={result['covered']}",
            {"phase": "verify_exclusions", "iteration": iteration,
             "tool": "lookup_policy_clause", "result": result},
        )
        return result

    tool_executor = {
        "verify_exclusion": _exec_verify_exclusion,
        "lookup_policy_clause": _exec_lookup_policy_clause,
    }

    response_schema = {
        "type": "object",
        "properties": {
            "whole_claim_excluded": {"type": "boolean"},
            "revised_lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "amount": {"type": "number"},
                        "excluded": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": ["whole_claim_excluded", "confidence", "rationale"],
    }

    prompt = (
        f"Adjudicate a health insurance claim.\n\n"
        f"Category: {state['category']}\n"
        f"Clinical text: {state['clinical_text'][:600]}\n"
        f"Keyword-matched exclusion terms: {state['matched_terms']}\n"
        f"Keyword verdict — whole_claim_excluded: {state['keyword_excluded']}\n\n"
        "Line items:\n"
        + "\n".join(
            f"  - {ln.get('description')} (Rs.{ln.get('amount')})"
            for ln in state["lines"][:10]
        )
        + f"\n\nPrior findings: {state['findings'][-2:]}\n\n"
        "Use verify_exclusion for each ambiguous matched term and lookup_policy_clause "
        "to read the full policy scope, then return your verdict."
    )

    tool_calls_made: list[dict] = []

    try:
        result = await llm.reason(
            prompt=prompt,
            tool_declarations=tool_declarations,
            tool_executor=tool_executor,
            response_schema=response_schema,
            on_tool_call=lambda name, args, res: tool_calls_made.append(
                {"tool": name, "args": args, "result": res}
            ),
        )

        confidence = float(result.get("confidence", 0.5))
        revised_excluded = result.get("whole_claim_excluded", state["keyword_excluded"])
        revised_lines = result.get("revised_lines") or state["lines"]
        rationale = result.get("rationale", "")

        emit(
            f"Pass {iteration}: excluded={revised_excluded}, confidence={confidence:.2f} — {rationale}",
            {"phase": "verify_exclusions", "iteration": iteration, "confidence": confidence},
        )
        return {
            "iteration": iteration,
            "tool_calls": tool_calls_made,
            "findings": [f"Pass {iteration}: {rationale} (confidence={confidence:.2f})"],
            "confidence": confidence,
            "revised_excluded": revised_excluded,
            "revised_lines": revised_lines,
            "rationale": rationale,
        }

    except Exception as exc:
        emit(f"Verification pass {iteration} failed: {exc}",
             {"phase": "verify_exclusions", "iteration": iteration, "error": str(exc)})
        return {
            "iteration": iteration,
            "tool_calls": tool_calls_made,
            "findings": [f"Pass {iteration} error: {exc}"],
            "confidence": 0.0,
        }


def _confirm(state: ReasonerState) -> dict:
    state["emit"](
        "Confirmed: keyword baseline is correct — no revision needed",
        {"phase": "confirm", "confidence": state["confidence"]},
    )
    return {
        "verdict": "CONFIRM",
        "rationale": state["rationale"] or "LLM reasoning confirms the keyword exclusion verdict.",
    }


def _override(state: ReasonerState) -> dict:
    state["emit"](
        f"Override: correcting coverage verdict — {state['rationale']}",
        {"phase": "override", "confidence": state["confidence"]},
    )
    return {"verdict": "OVERRIDE"}


def _escalate(state: ReasonerState) -> dict:
    state["emit"](
        f"Escalating to manual review after {state['iteration']} passes — confidence too low",
        {"phase": "escalate", "iterations": state["iteration"]},
    )
    return {"verdict": "ESCALATE"}


def _route(state: ReasonerState) -> str:
    if state["iteration"] >= MAX_ITERS:
        return "escalate"
    if state["confidence"] < CONFIDENCE_DECIDE:
        return "loop"
    lines_changed = state["revised_lines"] is not None and any(
        r.get("excluded") != o.get("excluded")
        for r, o in zip(state["revised_lines"] or [], state["lines"])
        if r.get("description") == o.get("description")
    )
    if state["revised_excluded"] == state["keyword_excluded"] and not lines_changed:
        return "confirm"
    return "override"


def _build_graph() -> Any:
    g: StateGraph = StateGraph(ReasonerState)
    g.add_node("load_context", _load_context)
    g.add_node("identify_ambiguity", _identify_ambiguity)
    g.add_node("verify_exclusions", _verify_exclusions)
    g.add_node("confirm", _confirm)
    g.add_node("override_coverage", _override)
    g.add_node("escalate", _escalate)

    g.set_entry_point("load_context")
    g.add_edge("load_context", "identify_ambiguity")
    g.add_conditional_edges(
        "identify_ambiguity",
        lambda s: "confirm" if not s["ambiguous"] else "verify_exclusions",
        {"confirm": "confirm", "verify_exclusions": "verify_exclusions"},
    )
    g.add_conditional_edges(
        "verify_exclusions",
        _route,
        {
            "confirm": "confirm",
            "override": "override_coverage",
            "escalate": "escalate",
            "loop": "verify_exclusions",
        },
    )
    g.add_edge("confirm", END)
    g.add_edge("override_coverage", END)
    g.add_edge("escalate", END)
    return g.compile()


_GRAPH = _build_graph()


def _clinical_text(bb: Blackboard) -> str:
    parts: list[str] = []
    for fact in bb.all():
        if fact.key.startswith("extraction."):
            content = (fact.value or {}).get("content") or {}
            for key in ("diagnosis", "treatment"):
                if content.get(key):
                    parts.append(str(content[key]))
    return " ".join(parts)


class PolicyReasonerAgent(GateGatedAgent):
    """LangGraph-powered policy reasoning agent.

    Fires after ExclusionAgent posts `coverage`. Runs a LangGraph StateGraph
    where Gemini uses tool calling to verify keyword-based exclusion decisions.
    Posts intermediate `policy_reasoning.step` facts in real time over SSE.
    """

    name = "policy_reasoner"
    reads = ["coverage"]
    writes = "policy_reasoning"

    def __init__(
        self,
        policy: Policy,
        llm_client: Any,
        on_post: Callable[[Fact], None] | None = None,
    ) -> None:
        self.policy = policy
        self.llm = llm_client
        self._on_post = on_post

    def _make_emit(self, bb: Blackboard) -> Callable[[str, dict], None]:
        def _emit(text: str, payload: dict) -> None:
            fact = bb.post(
                Fact(key="policy_reasoning.step", value={**payload, "text": text}, author=self.name),
                self,
            )
            if self._on_post:
                self._on_post(fact)
        return _emit

    async def _run(self, bb: Blackboard) -> Fact:
        from app.aggregator import DecisionAggregator

        coverage_fact = bb.get("coverage")
        coverage = coverage_fact.value if coverage_fact else {}
        emit = self._make_emit(bb)

        # Emit preliminary decision immediately so client gets a fast keyword-based answer
        prelim = DecisionAggregator(self.policy).decide(bb)
        prelim_fact = bb.post(
            Fact(
                key="preliminary_decision",
                value={
                    "status": prelim.status,
                    "label": f"{prelim.status} (pending policy verification)",
                    "approved_amount": str(prelim.approved_amount) if prelim.approved_amount else None,
                    "based_on": "keyword_baseline",
                },
                author=self.name,
            ),
            self,
        )
        if self._on_post:
            self._on_post(prelim_fact)

        # Offline / no reasoning-capable LLM → CONFIRM immediately, no reasoning loop
        if self.llm is None or not hasattr(self.llm, "reason"):
            return Fact(
                key="policy_reasoning",
                value={
                    "verdict": "CONFIRM",
                    "confidence": 1.0,
                    "iterations": 0,
                    "rationale": "LLM reasoning disabled; keyword baseline retained.",
                    "tool_calls": [],
                },
                author=self.name,
                confidence=1.0,
            )

        initial: ReasonerState = {
            "category": coverage.get("category", ""),
            "keyword_excluded": coverage.get("whole_claim_excluded", False),
            "matched_terms": coverage.get("matched_terms", []),
            "clinical_text": _clinical_text(bb),
            "lines": [dict(ln) for ln in coverage.get("lines", [])],
            "iteration": 0,
            "ambiguous": False,
            "tool_calls": [],
            "findings": [],
            "confidence": 0.0,
            "verdict": "",
            "revised_excluded": None,
            "revised_lines": None,
            "rationale": "",
            "emit": emit,
            "policy": self.policy,
            "llm": self.llm,
        }

        try:
            final = await _GRAPH.ainvoke(initial)
        except Exception as exc:
            return Fact(
                key="policy_reasoning",
                value={
                    "verdict": "CONFIRM",
                    "confidence": 0.0,
                    "iterations": 0,
                    "rationale": f"Reasoner failed ({exc}); keyword baseline retained.",
                    "tool_calls": [],
                },
                author=self.name,
                degraded=True,
                confidence=0.0,
            )

        verdict = final.get("verdict", "CONFIRM")

        # Total LLM failure: every pass threw (confidence=0.0, no tool calls made).
        # Degrade to CONFIRM so keyword baseline stands rather than mis-escalating.
        if (
            verdict == "ESCALATE"
            and final.get("confidence", 0.0) == 0.0
            and not final.get("tool_calls", [])
        ):
            return Fact(
                key="policy_reasoning",
                value={
                    "verdict": "CONFIRM",
                    "confidence": 0.0,
                    "iterations": final.get("iteration", 0),
                    "rationale": "LLM reasoning failed on all passes; keyword baseline retained.",
                    "tool_calls": [],
                },
                author=self.name,
                degraded=True,
                confidence=0.0,
            )

        if verdict == "OVERRIDE":
            new_lines = final.get("revised_lines") or coverage.get("lines", [])
            revised_excluded = final.get("revised_excluded", coverage.get("whole_claim_excluded"))
            covered = [ln for ln in new_lines if not ln.get("excluded")]
            excluded_lines = [ln for ln in new_lines if ln.get("excluded")]
            covered_amount = sum(Decimal(str(ln.get("amount", 0))) for ln in covered)
            revised = bb.post(
                Fact(
                    key="coverage.revised",
                    value={
                        "category": coverage.get("category"),
                        "lines": new_lines,
                        "covered_amount": str(covered_amount),
                        "covered_count": len(covered),
                        "excluded_count": len(excluded_lines),
                        "whole_claim_excluded": revised_excluded,
                        "matched_terms": coverage.get("matched_terms", []),
                        "message": final.get("rationale", ""),
                        "revised_from": "coverage",
                        "rationale": final.get("rationale", ""),
                        "tool_calls": final.get("tool_calls", []),
                    },
                    author=self.name,
                    confidence=final.get("confidence"),
                ),
                self,
            )
            if self._on_post:
                self._on_post(revised)

        elif verdict == "ESCALATE":
            flag = bb.post(
                Fact(
                    key="flag.ambiguity",
                    value={
                        "category": coverage.get("category"),
                        "matched_terms": coverage.get("matched_terms", []),
                        "iterations": final.get("iteration", 0),
                        "message": (
                            f"Coverage is genuinely ambiguous after "
                            f"{final.get('iteration', 0)} reasoning passes; "
                            "routing to manual review."
                        ),
                        "findings": final.get("findings", []),
                    },
                    author=self.name,
                    confidence=final.get("confidence"),
                ),
                self,
            )
            if self._on_post:
                self._on_post(flag)

        return Fact(
            key="policy_reasoning",
            value={
                "verdict": verdict,
                "confidence": final.get("confidence", 0.0),
                "iterations": final.get("iteration", 0),
                "rationale": final.get("rationale", ""),
                "tool_calls": final.get("tool_calls", []),
            },
            author=self.name,
            confidence=final.get("confidence"),
        )
