# Backend Execution Plan — build order, in parts

> **What this is:** the *order we build the backend in today*, as discrete parts. Each part ends in a
> **green signal** (something runs / N more test cases pass) so we always know exactly what is finished.
> **Companion:** `BUILD_PLAN_BACKEND.md` is the task reference (the `BE-x.y` IDs + acceptance criteria);
> this doc is the *sequence*. Architecture = `ARCHITECTURE.md`; logic = `PRD.md`.
> **Last updated:** 2026-06-21
>
> **Method:** walking skeleton first, then vertical slices. We do **not** build horizontal layers (all
> models → all agents → wire). Every part runs end-to-end and is verifiable before the next starts.
>
> **This is one continuous session — everything ships today.** The parts are a division for tractability
> and clean green signals, not a multi-day schedule. There are two stages: **Stage 1 (Parts 0–6)** makes
> the deterministic core *correct* (12/12 eval green, offline — no DB/Redis/SSE/LLM needed yet, content
> injection + a fake LLM client carry the suite); **Stage 2 (Parts 7–10)** makes it *live and deployed*.
> Both happen in the same sitting. The Gemini-vs-Claude question only surfaces at Part 7.

---

## Stage 1 — Parts 0–6 (correctness: 12/12 eval green, offline)

### PART 0 — Walking skeleton  *(~1 hr)*
**Goal:** prove the blackboard engine runs end-to-end.
**Build:**
- Scaffold: `app/{blackboard,agents,rules,llm,policy,eval}/`, `pyproject.toml`, `make test` (BE-0.1/0.2/0.5)
- `Fact` dataclass (BE-2.1) · `Blackboard` with `post/has/get`, per-claim `seq`, auto `derived_from` (BE-2.2)
- `Agent` base + `AgentState` (WAIT/READY/SKIP), `run()` never raises (BE-2.3)
- `adjudicate()` scheduler — the ~50-line loop (BE-2.5)
- **One toy agent** + one test that runs `adjudicate()` and asserts its fact

**✅ Done when:** `make test` is green — the engine fires one agent end-to-end. In-memory only.
**This proves:** the hardest, smallest piece (the scheduler) works. Everything after is additive.

---

### PART 1 — The rails: policy + eval harness + decision spine  *(~1.5 hr)*
**Goal:** the machinery every test case runs on. (The only part that doesn't add green cases — it makes the *harness* able to grade them.)
**Build:**
- `Settings` + env (BE-0.3, minimal)
- **Policy loader** — reads `policy_terms.json`, exposes key *paths*, **zero hardcoded values** (BE-1.4/1.5)
- `MemberResolver` (roster lookup) + `IntakeValidator` (min amount; deadline disabled) (BE-4.1/4.2)
- `DecisionAggregator` — precedence ladder skeleton (PRD §5): produces `BLOCKED/REJECTED/MANUAL_REVIEW/PARTIAL/APPROVED` from whatever verdict facts exist (BE-4.19, partial)
- `GateGatedAgent` mixin (BE-2.4) · `skipped.*` resolver (BE-2.6)
- **Eval harness**: test-case loader (BE-6.1) + runner that asserts status + amount + reasons (BE-6.2)

**✅ Done when:** `make eval` loads all 12 cases and runs each through `adjudicate()`, asserting against expected. Expect **0/12 green** here — but every case *executes* and the asserts are wired. Policy accessor resolves every key PRD §6 cites.
**This proves:** the grading rails work, and policy is data (swap the JSON → behavior changes, no code change).

---

### PART 2 — Gate slice → **TC001, TC002, TC003 (3/12)**  *(~1.5 hr)*
**Goal:** the collect-all document gate (edge #1).
**Build:**
- `DocDetector` + `Extractor` in **offline mode** — for gate cases, inject the case's doc metadata (`actual_type`, `quality`→readable, `patient_name_on_doc`) as `extraction.*` / `segment.*` facts (BE-4.6/4.7, injection path)
- **`DocGate`** — collect-all, report-once (PRD §4.3): readability, required-types (vs `policy.document_requirements[cat]`), patient-match (member OR dependent), missing-critical-field; dependency rule (unreadable ⇒ skip type/patient for that doc) (BE-4.8)
- Patient match needs dependents from the roster (PRD §8.5)

**✅ Done when:** **3/12 green** — TC001 (missing bill), TC002 (unreadable bill), TC003 (patient mismatch) all return `BLOCKED` with the *full* issue list in one message.
**This proves:** our flagship gate behavior + the BLOCKED path through the aggregator.

---

### PART 3 — Clean approvals → **TC004, TC010 (5/12)**  *(~1.5 hr)*
**Goal:** the financial calculator — order is load-bearing.
**Build:**
- `SemanticMapper` (minimal: category match, line classification) (BE-4.9)
- `FinancialReconciler` → `financial_facts` (lines, bill_total, line_sum, divergence) (BE-4.11)
- **`FinancialCalculator`** → `financial_breakdown`: **network discount → co-pay → sub-limit cap**, all `decimal.Decimal`; emits every step with `{pct, amount, applied, policy_ref}` (BE-4.18; schema ARCHITECTURE §6.3)
- Aggregator now emits `APPROVED` + amount

**✅ Done when:** **5/12 green** — TC004 = ₹1,350 (no network, 10% copay); TC010 = ₹3,240 (Apollo −20% then −10%, order proven).
**This proves:** the money math is exact and the discount-before-copay order is correct.

---

### PART 4 — Definitive rejects → **TC005, TC007, TC008, TC012 (9/12)**  *(~2 hr)*
**Goal:** the four rule agents that reject, plus reason ranking.
**Build:**
- `WaitingPeriodAgent` (PRD §4.5) — TC005 (44 days < 90 diabetes) (BE-4.13)
- `PreAuthAgent` (PRD §4.7) — TC007 (MRI ₹15k > ₹10k, no pre-auth) (BE-4.15)
- `PerClaimLimitAgent` (PRD §4.8) — TC008 (covered ₹7,500 > per-claim ₹5,000, hard reject) (BE-4.3)
- `ExclusionAgent` whole-claim (PRD §4.6a) — TC012 (obesity/bariatric) (BE-4.14)
- Reason ranking in aggregator: EXCLUDED > WAITING > PRE_AUTH > PER_CLAIM (PRD §5 / §8.2 B2)
- Adaptive guards: waiting/pre-auth SKIP when provably PASS (BE-4.22)

**✅ Done when:** **9/12 green** — all four return `REJECTED` with the correctly-ranked primary reason (TC012 shows EXCLUDED over PER_CLAIM).
**This proves:** the rule engine + precedence resolution.

---

### PART 5 — Partial → **TC006 (10/12)**  *(~1 hr)*
**Goal:** line-item exclusion + the category-aware cap.
**Build:**
- `ExclusionAgent` line-item path (PRD §4.6b): disallow the excluded line, keep the rest
- The **`max(per_claim_limit, category sub_limit)`** interpretation in PerClaimLimit + calc (PRD §4.8) — dental sub_limit ₹10k > per-claim ₹5k, so ₹8k caps not rejects
- Aggregator emits `PARTIAL`

**✅ Done when:** **10/12 green** — TC006 = `PARTIAL ₹8,000` (root canal covered, whitening line excluded).
**This proves:** the subtlest interpretation call — the one a naive ">₹5,000 reject" gets wrong.

---

### PART 6 — Fraud + degraded → **TC009, TC011 (12/12) 🎉**  *(~1.5 hr)*
**Goal:** close the suite — fraud velocity + graceful degradation.
**Build:**
- `VelocityFraudAgent` + **claims ledger** with **per-case eval isolation** (seeded from `claims_history`, resets per case) (BE-4.5/4.24) — TC009 (4th same-day → `MANUAL_REVIEW`)
- `HighValueAgent` (BE-4.4) · `DocumentFraudAgent` stub (BE-4.17)
- **Graceful degradation overlay** (PRD §4.14): inject a non-critical component failure → keep status, lower confidence, add manual-review *note* — TC011 stays `APPROVED ₹4,000`
- **Confidence model** (BE-4.23): tune to hit TC004 > 0.85, TC012 > 0.90, TC011 measurably lower
- 50-run stability check: same fact-set + decision every run (BE-2.7)

**✅ Done when:** **12/12 green** + stable across repeats. **← Milestone A reached. Backend is correct.**
**This proves:** fraud routing, the degraded-but-approved distinction, and determinism.

---

> **Stage 1 complete = the backend is correct.** This is the natural checkpoint — 12/12 green — but we
> don't stop here; we roll straight into Stage 2 in the same session. The value of the checkpoint is that
> if energy/time gets tight, correctness is already banked: even a non-deployed 12/12 system is a passing
> submission. Everything in Stage 2 makes it *impressive*, not *correct*.

---

## Stage 2 — Parts 7–10 (live & deployed)

### PART 7 — Real extraction (vision)
Gemini Flash adapter behind the `LLMClient` protocol (BE-3.1/3.2), extraction cache (BE-3.4), document binning (BE-3.5), self-correction re-read (BE-3.6), render 2–3 docs for a **live** vision pass (BE-6.4).
**✅ Done when:** a real rendered doc extracts through Gemini with a live confidence; the deterministic suite still 12/12 via the fake client.
*(This is where the Gemini-vs-Claude decision gets made — one adapter swap.)*

### PART 8 — Persistence + API + SSE
DB models + Alembic (BE-1.1/1.2/1.3), persist hook (BE-5.1), Redis pub/sub (BE-5.2), `POST /claims` as background task (BE-5.3), `GET /claims/{id}` (BE-5.4), `GET /claims/{id}/stream` SSE (BE-5.5), CORS (BE-5.6), never-500 envelope (BE-5.7).
**✅ Done when:** submit returns a `claim_id` in ms; facts persist + stream live; refresh resumes.

### PART 9 — Deploy
Supabase (direct DSN) + Upstash + Render (BE-7.1–7.3), smoke test on the public URL (BE-7.4).
**✅ Done when:** a real claim adjudicates on the deployed backend, streaming live.

### PART 10 — Harden + observe + docs
Degradation proof polish (BE-8.1), trace quality (BE-8.2), §8.6 production scenarios (BE-8.3), 10x-load story → FUTURE_DIRECTIONS (BE-8.4), README + demo script (BE-8.5), logging/health (BE-8.6).
**✅ Done when:** demo-ready, observable, with the scaling story told.

---

## At-a-glance

| Part | Ends with | Cumulative | Stage |
|------|-----------|------------|-------|
| 0 | engine runs, 1 toy agent green | skeleton | 1 |
| 1 | eval harness grades all 12 | 0/12 (rails) | 1 |
| 2 | gate cases | **3/12** | 1 |
| 3 | clean approvals | **5/12** | 1 |
| 4 | definitive rejects | **9/12** | 1 |
| 5 | partial | **10/12** | 1 |
| 6 | fraud + degraded | **12/12 ✅ correct** | 1 |
| 7 | real vision extraction | 12/12 + live LLM | 2 |
| 8 | persistence + API + SSE | live service | 2 |
| 9 | deployed | public URL | 2 |
| 10 | hardened + docs | demo-ready | 2 |

**Rule for the session:** never move to the next part until the current part's green signal is real. The number on the board only goes up. Correctness (Stage 1) is banked before polish (Stage 2) begins — so the submission is already passing well before the session ends.
