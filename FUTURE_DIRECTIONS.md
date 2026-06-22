# Future Directions (deferred from the 2–3 day build)

> Things deliberately **cut** from the build, with the reasoning, so the trade-off is a conscious one
> (the assignment rewards judgment about what to cut). Each entry says: what it is, why deferred,
> what it would take, and how it plugs into the existing design without breaking its guarantees.

---

## FD-1. Adaptive / learning fraud engine

### What exists today (in scope — built)
A **deterministic claims ledger** (PRD §4.9): every processed claim is recorded keyed by member (and provider/hospital). Velocity checks query it; repeat-offender and known-bad-provider checks are deterministic lookups. The fraud *verdict* is code, not an LLM call — fully reproducible.

### What this future direction adds
The part that **learns and evolves** instead of applying fixed thresholds:

- **Entity risk scoring** — a continuously-updated risk score per member and per provider/hospital, derived from their full claim history (approval/rejection/manual-review outcomes), not a single same-day count.
- **Provider collusion / fraud-ring detection** — a graph over members ↔ providers ↔ diagnoses; dense or anomalous subgraphs (e.g. one clinic generating many borderline claims across unrelated members) surface rings that per-claim rules cannot see.
- **ML anomaly scoring** — an outlier model over claim features (amount vs peers for the same diagnosis, unusual treatment/diagnosis pairings, timing patterns) that flags claims no static threshold would catch.
- **Repeat-offender escalation curves** — escalating scrutiny for entities with a history of rejected/flagged claims, instead of treating every claim as the entity's first.

### Why it is deferred (not built now)
1. **The eval doesn't test it.** All 12 cases hand fraud history to the system as *input* (`claims_history`, `ytd_claims_amount`). None test cross-claim learning. Building it would be speculative scaffolding for the grade.
2. **No data to learn from.** There is no fraud-labeled corpus and a static 12-member roster — a learning model has nothing to train on in this assignment.
3. **Learning fights reproducibility.** A behavior that changes over time is the enemy of an explainable, replayable trace (Observability = 20% of the grade). It must not be bolted on without the guardrails below.
4. **Time.** The 2–3 day window is better spent making the non-negotiables (extraction, gate, decision, explainability, eval) excellent.

### How it would plug in (without breaking current guarantees)
- It contributes an **additional evidence score into the existing deterministic scorer** — it does **not** become the decision-maker. The final routing stays code: "model risk ≥ threshold → FLAG → MANUAL_REVIEW," same shape as today's Track 2.
- **Human-in-the-loop is the training signal.** Ops decisions on `MANUAL_REVIEW` claims become labels, closing the feedback loop the assignment's "10x lives" framing implies.
- **Reproducibility guardrail:** every decision trace snapshots the **model version + exact feature values used**, so any past decision can be replayed precisely even after the model has moved on.

### What it would take (10x-load build)
- Feature store + model registry; offline training + eval harness with labeled outcomes.
- Streaming feature computation so entity scores stay fresh without slowing the real-time path (scores are read from a cache on the critical path, computed asynchronously off it).
- Drift monitoring + alerting; periodic re-validation against held-out labels.
- A graph store (or graph queries over the relational ledger) for ring detection.

### Ties to the assignment
- **System Design (30%)** — answers "how would you address it at 10x load" with a concrete, staged evolution rather than a rewrite.
- **Multi-agent bonus** — the fraud engine is an autonomous, *stateful* component with a lifecycle beyond a single claim; the learning layer makes it genuinely intelligent rather than a counter.
- **Strong technical-review / demo talking point** — "one decision I'd extend given more time," with the determinism/explainability trade-off already reasoned through.
