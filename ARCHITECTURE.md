# Claims Processing System — Architecture

> **Status:** Architecture **LOCKED → Multi-Agent Blackboard (B-static)**. The phased pipeline (A) is retained as a *fallback only* (§7.9).
> **Last updated:** 2026-06-21 (rev 9 — all gaps resolved; deployment stack locked; CORS + API→Worker handoff specified)
> **Reference studied:** `github.com/jd316/plum-claims` — **a prior submission that cleared this round.** Studied for honest competitive positioning; not copied.
> **Logic contract:** `PRD.md` owns all rule logic and interpretation calls. This document owns *how* that logic is executed; it does **not** re-state the rules. `DIAGRAMS.md` holds the visual flows.

---

## 0. The decision, up front

- **We build B-static** — a blackboard (shared fact store + autonomous agents that fire when their inputs exist) **without fact re-firing**: each agent fires at most once; extraction self-corrects *internally* before it posts, so no fact is ever re-derived downstream.
- **Why** (full rationale §8): it's the only model that serves *both* of our goals at once, it earns the multi-agent bonus, and dropping re-firing keeps it deterministic and testable in a 2–3 day build.
- **Fallback:** Architecture A (phased pipeline) — same agents, same contracts, barriers instead of fact-triggered activation. If the scheduler stalls mid-build, we degrade to A cheaply (§7.9).

**Primary goals driving every choice:**
1. **Fastest possible response** — an immediate signal/decision, not a spinner.
2. **Highest extraction confidence** — messy Indian medical docs read as accurately as possible.

These two are in tension (max confidence = more LLM passes = more time). B-static resolves it by letting **each agent declare its own confidence tolerance** — see §8.2.

---

## 1. Vision

A claims processing system that:
- Feels **genuinely multi-agent** — parallel agents visibly working, not a black box.
- Gives a **real-time illusion** — the user sees progress and early verdicts as they happen.
- Makes **fully explainable decisions** — every check, output, and reason is traceable to the policy key it used.
- **Degrades gracefully** — a component failure is a recorded/missing fact, never a crash; confidence drops accordingly.
- **Ships with rigor** — tests per component, a deployed URL, and a pipeline that never 500s (the bar the reference already met).

---

## 2. Guiding Principles

| # | Principle | Implication |
|---|-----------|-------------|
| 1 | **Submit returns in milliseconds** | HTTP response is a `claim_id`, never the result. Processing runs as a background task. |
| 2 | **LLM proposes, deterministic code decides** | LLM classifies, extracts, maps, and acts as advisory verifier. **All arithmetic and all verdicts are deterministic Python.** Same facts → same decision. |
| 3 | **Policy is data** | Every rule reads from the injected `policy_terms.json` (PRD §2.1). Nothing hardcoded. |
| 4 | **Stream everything** | Each fact emits an SSE event the instant it is posted. |
| 5 | **Persist immediately** | Each fact is written to the DB as it is produced (survives crashes, queryable mid-flight). |
| 6 | **Fail gracefully, always** | A failure is a recorded degraded fact, not a crash. The reference converts *any* unhandled error into a degraded `MANUAL_REVIEW`; we match that. |
| 7 | **Ship like it's graded on running, not designing** | Every component has tests; the system is deployed; Day 1 success = all 12 cases pass on a running system. |

---

## 3. Competitive Differentiation (honest read of the cleared reference)

> The reference is strong and cleared deservedly. "Surpassing" is not about features he didn't think of — he thought of most. It is about (a) **not regressing** on what he nailed, (b) executing the **genuine edges** he lacks, and (c) **absorbing** the two things he has that we otherwise wouldn't.

### 3.1 What the reference already does well → **do NOT regress on these**

| Capability | Evidence in his code |
|-----------|----------------------|
| Config-driven policy engine; every verdict carries `policy_refs` | `services/policy_engine.py`, `rules/*.py` |
| **Policy versioning + live policy editing** | migration `0005_policy_versions.py`, `policy_store.py`, `PolicyStudio.tsx` |
| Per-claim-limit × sub-limit subtlety — **config-switchable**, on the *covered* amount | `rules/limits.py` (`settings.sub_limit_scope`) |
| Semantic mapping + LLM-as-judge verifier (advisory; can only force MANUAL_REVIEW) | `agents/semantic_map.py`, `agents/verifier.py` |
| Parallel fan-out (per-doc extraction, per-rule checks) via LangGraph `Send` | `graph/build.py` (`max_concurrency`) |
| Graceful never-crash (any exception → degraded MANUAL_REVIEW) | `graph/build.py::run_claim` |
| Polished document gate: WRONG vs MISSING vs INCOMPLETE, LAB/DIAGNOSTIC equivalence, member-friendly labels | `rules/docgate.py` |
| **Policy RAG assistant** — grounded answers, citations, prompt-injection sanitization | `services/policy_rag.py` |
| **Adaptive supervisor** — *provably-safe* rule skipping (skips a rule only when proven to PASS) | `graph/supervisor.py` |

> Implication: config-driven rules, policy versioning, and the per-claim subtlety are **table stakes against him**, not differentiators. We must match them, then win elsewhere.

### 3.2 Where we genuinely surpass → **our real edges (verified in his code)**

1. **Collect-all document gate.** His `docgate.py` returns the *first problem category* and stops (`if problems: return problems` after each step) — a member with three independent problems fixes them over three resubmissions. **Ours collects every member-solvable problem and reports once** (PRD §4.3). Concrete win on Document Verification (10%) + member experience.
2. **Cross-document clinical coherence (claim synthesis).** He checks patient *names* match (`identity.py`) and decision-vs-verdict consistency (`verifier.py`) — but **nobody validates the clinical chain**: diagnosis ↔ ordered tests ↔ billed items ↔ date sanity. This is our deepest edge on AI Integration (15%) + System Design.
3. **True concurrency.** His parallelism is *barriered* — `defer=True` on docgate and financial forces a rendezvous; the supervisor is a phase. **Our blackboard removes the barriers**: velocity-fraud fires at intake while extraction runs; each rule activates the instant its facts exist. Earns the multi-agent bonus and powers the real-time UX.
4. **Real-time agent-streaming UX.** The board *is* the UI — facts light up and early verdicts pop before the claim fully resolves. A visibly different experience from request→response.

### 3.3 What we must ABSORB → **so we don't lose on his strengths**

- **Adaptive provably-safe skip** — maps *natively* onto the blackboard as agent **preconditions**: an agent simply does not fire when its guard proves PASS (e.g. `pre_auth` for a non-diagnostic category; `waiting_period` when enrolled beyond the policy's max waiting). Same optimization, emergent rather than bolted on — a cleaner story than his supervisor.
- **Ship rigor** — tests per component, deployed URL, never-500s (principle 6/7).

> **Deliberately NOT matching: his policy RAG assistant.** It's a *peripheral* feature — a policy Q&A side-panel that never touches a claim decision. We concede it on purpose: our AI-Integration weight (15%) is carried by work *on the core flow* — clinical-coherence synthesis (edge #2) and structured, self-correcting, validated extraction — which is deeper and more defensible than a bolt-on Q&A box. Cutting it also removes an embedding index, an injection-sanitization surface, and an entire code path from the 2–3 day build. A conscious trade-off, not an oversight.

---

## 4. Architectural Posture (what we do differently at the system level)

| Concern | Typical phased/DAG build | Our posture (B-static) |
|---------|--------------------------|------------------------|
| HTTP | One blocking request until END (his `GRAPH.invoke`) | Submit returns `claim_id`; processing is a background async task |
| Streaming | Blocks until the graph completes | Redis pub/sub → SSE delivers each fact as it posts |
| Orchestration | LangGraph StateGraph + barriers | Plain ~40-line asyncio blackboard scheduler — full control of the event stream |
| Intermediate state | Held in memory, written once at end | Every fact persisted the instant it is produced (the `facts` table *is* the trace) |
| Shared state | Per-process (circuit breaker, cache, policy) | Shared in Redis (content-addressed extraction cache across workers) |
| Self-correction | On the critical path | Background; the draft proceeds, the corrected fact merges before it is consumed (no re-firing) |
| File storage | Local FS (breaks with multiple workers) | Supabase Storage (S3-compatible, free 1 GB) — same platform as DB |

---

## 5. Tech Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Backend | Python 3.12+, FastAPI (async) | Native SSE, async handlers; persistent process required for SSE + background workers |
| LLM | **Gemini Flash (Google) — all agents** | Vision + structured output; Flash used uniformly across all agent roles |
| Event bus | **Upstash Redis** (serverless, free 10k req/day) | Drop-in Redis pub/sub + cache; works from Render and Vercel; no Docker in prod |
| Shared cache | Upstash Redis | Content-addressed extraction cache: key = `sha256(file_bytes)`, value = `ExtractionResult`, TTL 24 h |
| Database | **Supabase** PostgreSQL (free 500 MB) + SQLAlchemy (async) | Use direct connection URL (not pooler) for SQLAlchemy async; Alembic unchanged |
| Migrations | Alembic | Runs on deploy via `alembic upgrade head`; targets Supabase direct connection string |
| File storage | **Supabase Storage** (S3-compatible, free 1 GB) | Same platform as DB — one dashboard, one set of credentials; `stored_path` stays a bucket key; swap MinIO client → boto3 with Supabase S3 endpoint |
| Frontend | **Next.js 15** (App Router) + TypeScript + Tailwind | SSE via `EventSource` works identically; replaces React 19 standalone |
| Streaming | SSE (EventSource) | Simple unidirectional server→client |
| Containers | Docker + Docker Compose (local dev only) | Local: 5 services (API, Frontend, Redis, PostgreSQL, MinIO). No separate Worker — adjudication runs as `asyncio.BackgroundTasks` inside the API process. |
| Backend deploy | **Render** (free web service) | Single persistent FastAPI process handles HTTP + background adjudication tasks; auto-deploys from GitHub; sleeps after 15 min idle — hit URL once before demo |
| CORS | `fastapi.middleware.cors.CORSMiddleware` | Required — browser on Vercel domain calls Render domain directly. Allow Vercel origin + `*` for local dev. Without this every browser request is silently blocked. |
| Frontend deploy | **Vercel** (hobby, free) | First-class Next.js; auto-deploys from GitHub. **All API calls and `EventSource` must point directly at the Render backend URL — never proxied through a Next.js API route.** Vercel Hobby serverless functions time out at 10 s; an SSE proxy through `/api/*` would be killed mid-stream. |
| Auth | None for demo | Endpoints are open; API key can be added post-demo without changing logic |

---

## 6. Shared Execution Concerns

### 6.1 LLM agents vs deterministic core
The LLM only: detects document type, extracts fields (per-field confidence + `source_text`), maps free text → policy vocabulary, surfaces perceptual anomaly signals, and acts as an advisory verifier. **All arithmetic and all verdicts are deterministic Python.**

### 6.2 The policy checks
`waiting_period · coverage_exclusion · pre_auth · limits · fraud_anomaly` — **logic owned by `PRD.md` §4.5–§4.9.** Each is a blackboard agent that posts a `verdict.*` fact. Adaptive guards (§3.3) prevent an agent from firing when it provably PASSes.

**Verifier scope:** `Verifier` fires only when `DecisionAggregator` posts `APPROVED` or `PARTIAL`. It is skipped (via adaptive guard → SKIP fact) on `REJECTED`, `BLOCKED`, and `MANUAL_REVIEW` outcomes — no value in re-checking evidence on a definitive denial.

### 6.3 Financial calculation
Order is load-bearing — **network discount → co-pay → sub-limit cap**, all `decimal.Decimal`. Full spec: `PRD.md` §4.10 (incl. the line-items↔total reconciliation step).

**Two-agent split:**
- `FinancialReconciler` reads all `extraction.*` facts and posts `financial_facts` — the reconciled, cleaned input for calculation:
  ```json
  {
    "lines":             [{"item": "...", "billed": "Decimal", "source_doc": "extraction.{id}"}],
    "bill_total":        "Decimal  (from extraction)",
    "line_sum":          "Decimal  (Σ lines)",
    "divergence_flagged": "bool    (true if |bill_total - line_sum| > threshold)"
  }
  ```
- `FinancialCalculator` reads `financial_facts` + all `verdict.*` facts and posts `financial_breakdown` (§6.3 output schema above). `DecisionAggregator` reads only `approved_amount` from it.

`FinancialCalculator` emits a single `financial_breakdown` fact whose `value` carries every intermediate step so that both the member-facing UI and the audit trail know *how much* was deducted and *why*:

```json
{
  "lines": [
    {"item": "Root Canal",      "billed": 8000, "status": "covered"},
    {"item": "Teeth Whitening", "billed": 4000, "status": "excluded",
     "policy_ref": "opd_categories.dental.excluded_procedures[1]"}
  ],
  "gross": 8000,
  "network_discount": {"pct": 0,   "amount": 0,   "applied": false,
                       "policy_ref": "opd_categories.dental.network_discount_percent"},
  "copay":            {"pct": 0,   "amount": 0,   "applied": false,
                       "policy_ref": "opd_categories.dental.copay_percent"},
  "sublimit_cap":     {"cap": 10000, "amount": 0, "applied": false,
                       "policy_ref": "opd_categories.dental.sub_limit"},
  "approved_amount":  8000
}
```

Every deduction step emits `{pct, amount, applied, policy_ref}` even when `applied: false` — so the UI can show "no co-pay because dental is 0%" rather than silently omitting the line. `DecisionAggregator` reads `approved_amount` from this fact; the frontend SSE stream surfaces the full object for the real-time breakdown panel.

### 6.4 Document gate
Deterministic, **collect-all** (PRD §4.3) — runs after extraction, reports every member-solvable problem at once. This is edge #1 (§3.2).

### 6.5 Database
Single `facts` table (claim_id, seq, key, author, value JSONB, confidence, derived_from[], degraded, tokens, duration, policy_version_id) — both the working store and **the complete audit trail**. No separate `audit_log` table — facts table is authoritative.

Other tables: `claims`, `claim_documents`, `claim_decisions`, `policy_versions`.

**`policy_versions`** stores `{id, loaded_at, content JSONB}`. Every fact carries `policy_version_id` so an ops reviewer can see exactly which policy version adjudicated a claim. No editor UI — version-stamp-in-trace only.

**`seq`** is a per-claim atomic counter assigned by `bb.post()` before the fact is persisted. Monotonic per claim; independent of DB insert order. Sort by `seq` for canonical replay.

### 6.6 Document binning
`DocDetector` processes each uploaded file. For PDFs it classifies each page's document type, then **bins** consecutive pages of the same type into one logical segment. Pages that form a front/back of the same physical document (same type, adjacent pages) are also binned together. A page classified as a different type starts a new segment. Single-image uploads are a single segment with no binning needed.

Example: a 3-page PDF — [PRESCRIPTION, PRESCRIPTION, HOSPITAL_BILL] → two segments: `segment.0` (pages 1–2, PRESCRIPTION) + `segment.1` (page 3, HOSPITAL_BILL).

Each segment becomes one `segment.*` fact consumed by `Extractor`.

### 6.7 SSE event schema
Every fact posted to the blackboard emits a full SSE event immediately. Shape:
```json
{
  "claim_id":         "uuid",
  "seq":              "int  (per-claim monotonic counter)",
  "key":              "string  (e.g. 'verdict.pre_auth', 'skipped.waiting_period')",
  "author":           "string  (agent name or 'intake')",
  "value":            "object  (fact payload — varies by key)",
  "confidence":       "float | null",
  "degraded":         "bool",
  "derived_from":     ["fact_key", ...],
  "policy_version_id":"uuid",
  "reason":           "PROVABLY_PASS | GATE_BLOCKED | GUARD_FIRED | null  (skipped facts only)"
}
```
Frontend subscribes to `GET /claims/{id}/stream`. Redis channel: `claims:{claim_id}`.

### 6.8 API endpoints (day 1)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/claims` | Submit claim + documents. Returns `{claim_id}` immediately; adjudication runs as background task. |
| `GET`  | `/claims/{id}` | Full claim state: submission fields + current decision + all facts (sorted by seq). |
| `GET`  | `/claims/{id}/stream` | SSE stream — emits one event per fact as it posts. Closes when `decision` fact is posted. |

No auth on any endpoint for the demo.

### 6.9 Extraction cache
Key: `sha256(file_bytes)` (hex string). Value: serialised `ExtractionResult` (doc_type, fields with per-field confidence + source_text, readable flag, quality issues). TTL: 24 h. Stored in Redis. If a cache hit is found, `Extractor` skips the Gemini call and posts the cached result directly. Cache is category-agnostic — same file bytes produce the same extraction regardless of claim category.

### 6.10 Eval isolation (claims ledger)
The velocity fraud check (PRD §4.9) reads a claims ledger. For eval, the ledger is seeded from the `claims_history` array in each test case payload and held in memory scoped to that claim's adjudication. It never reads from the DB claims table during velocity checks. This prevents state bleed across eval runs and allows parallel test-case execution.

### 6.11 Confidence threshold
A confidence score below **0.70** (hardcoded) triggers `MANUAL_REVIEW` escalation at the `DecisionAggregator` stage, per PRD §5 rule 3.

### 6.12 Verified product logic — *see PRD*
> All interpretation calls (per-claim × sub-limit, exclusion vs limit precedence, dental-report contradiction, submission-deadline trap, MANUAL_REVIEW-vs-note distinction), the test-case ingestion decision, and the confidence-score constraints are **specified and validated in `PRD.md` §4, §5, §8**. Not duplicated here, to keep one source of truth.
>
> Two architecture-relevant notes that live here because they shape the build:
> - **Test-case ingestion:** support both (a) render synthetic docs + real vision for a few cases to *prove* extraction confidence, and (b) content-injection for the deterministic full suite. (PRD §8.4.)
> - **Confidence model:** component-based — extraction quality · rule certainty · completeness · verifier agreement − degradation penalty — must hit TC004 > 0.85, TC012 > 0.90, TC011 measurably lower. (PRD §4.13.)

---

## 7. The Architecture — Multi-Agent Blackboard (B-static)

No phases. A shared append-only **fact store** (the blackboard) + autonomous **agents** that each declare the facts they need (`reads`) and the fact they produce (`writes`). A ~40-line scheduler fires every agent the instant its preconditions appear. **B-static = no re-firing:** each agent fires at most once; extraction self-corrects internally before posting, so no downstream fact is ever re-derived. Lineage: Hearsay-II, classic expert systems.

### 7.1 Fact dependency graph

```
submission ──┬─► MemberResolver ───────────────► member
             ├─► PerClaimLimitAgent ───────────► verdict.limits.per_claim   [INSTANT — TC008]
             ├─► HighValueAgent ───────────────► verdict.fraud.high_value   [INSTANT]
             └─► VelocityFraudAgent (+member) ─► verdict.fraud.velocity     [INSTANT — TC009]
                   (reads the persistent claims ledger; PRD §4.9)
documents ───► DocDetector×file ──────────────► segment.*  ──► Extractor×segment ──► extraction.{id}
                                                                    │  (self-corrects internally
                                                                    │   before posting — no re-fire)
                              DocGate (all segments+extractions) ─► gate.passed | gate.blocked
                                   COLLECT-ALL: reports every problem at once  [TC001–003; edge #1]
                                                                    │ (gate.passed gates all below)
  extraction.Rx ─► SemanticMapper ────────────► semantic_map
  extractions ──► PatientResolver ────────────► patient_identity
  bills ────────► FinancialReconciler ────────► financial_facts
  extractions ──► ClinicalChainAgent ─────────► clinical_chain   [edge #2 — coherence he lacks]
        │
        ├─ (member + semantic_map) ──────────► WaitingPeriodAgent  → verdict.waiting_period   [TC005]
        ├─ (semantic_map + clinical) ────────► ExclusionAgent      → verdict.exclusion        [TC006/12]
        ├─ (financial_facts + semantic) ─────► PreAuthAgent        → verdict.pre_auth         [TC007]
        ├─ (financial_facts + member) ───────► AggregateLimitsAgent→ verdict.limits.aggregate
        └─ (patient_identity + clinical) ────► DocumentFraudAgent  → verdict.fraud.document
                                                     │
  (financial_facts + all verdicts) ─► FinancialCalculator ─► financial_breakdown   [TC010 order]
  (all verdicts + breakdown) ─► DecisionAggregator ─► decision   (precedence: PRD §5)
  (decision + extractions) ─► Verifier ─► verifier_result → may escalate to MANUAL_REVIEW   [async]

  Adaptive guards (§3.3): WaitingPeriodAgent / PreAuthAgent carry a `ready()` predicate that
  resolves to a SKIP fact (provably PASS) instead of firing — e.g. pre_auth on a non-diagnostic
  category, or waiting_period when enrolled beyond the policy's max waiting window.
  Verifier guard: resolves to SKIP when decision is REJECTED / BLOCKED / MANUAL_REVIEW.

  ClinicalChainAgent — 3 coherence checks (edge #2):
    1. Patient consistency: same patient across Rx + lab + bill (feeds PatientResolver cross-check)
    2. Date ordering: Rx date ≤ lab date ≤ bill date (sane episode)
    3. Test-bill alignment: tests ordered in Rx ≈ tests performed in lab ≈ items billed
    Posts: clinical_chain { coherence_score, signals: [{type, description}] }
    Consumed by: ExclusionAgent, DocumentFraudAgent

  PatientResolver name matching (two-stage):
    Stage 1: token overlap ≥ 50% → MATCH (no LLM)
    Stage 2: if overlap < 50% → Gemini Flash structural comparison with Indian naming conventions
    Stage 3: if LLM also says mismatch → MISMATCH (reported in gate issues)
```

### 7.2 Defining property
**Each agent fires at the earliest instant its evidence exists** — bounded only by real data dependencies, never by phase barriers. TC008/TC009 verdicts land at `t≈0`; TC005 decides the moment the prescription is read + mapped, never waiting for the bill.

### 7.3 The scheduler (~50 lines)

```python
class AgentState(Enum):
    WAIT  = "wait"    # preconditions not yet on board — keep polling
    READY = "ready"   # all inputs exist — fire now
    SKIP  = "skip"    # will never be needed — post a skip fact and prune

async def adjudicate(submission, timeout_s: int = 120) -> Blackboard:
    bb = Blackboard(); bb.post("submission", submission, author="intake")
    pending, running = set(build_agents()), {}
    deadline = asyncio.get_event_loop().time() + timeout_s

    while pending or running:
        for a in list(pending):
            state = a.ready(bb)
            if state == AgentState.SKIP:
                pending.discard(a)
                skip_fact = Fact(key=f"skipped.{a.name}",
                                 value={"reason": a.skip_reason(bb)},   # PROVABLY_PASS | GATE_BLOCKED | GUARD_FIRED
                                 author=a.name, degraded=False)
                bb.post(skip_fact); await emit_sse(skip_fact); await persist(skip_fact)
            elif state == AgentState.READY:
                pending.discard(a); running[a] = asyncio.create_task(a.run(bb))

        if not running:
            break

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:                         # wall-clock timeout — drain remainder as degraded
            for a in list(pending):
                degraded = Fact(key=f"skipped.{a.name}",
                                value={"reason": "TIMEOUT"},
                                author=a.name, degraded=True)
                bb.post(degraded); await emit_sse(degraded); await persist(degraded)
            pending.clear()
            break

        done, _ = await asyncio.wait(running.values(),
                                     return_when=asyncio.FIRST_COMPLETED,
                                     timeout=remaining)
        for task in done:
            a = owner(task); fact = task.result()
            bb.post(fact); await emit_sse(fact); await persist(fact)
            del running[a]

    return bb
```

**Agent contract:**
```python
class Agent:
    name:  str
    reads: list[str]              # fact keys this agent consumes
                                  # bb.post() auto-sets derived_from = self.reads

    def ready(self, bb) -> AgentState: ...   # WAIT / READY / SKIP
    def skip_reason(self, bb) -> str:   ...  # PROVABLY_PASS | GATE_BLOCKED | GUARD_FIRED
    async def run(self, bb) -> Fact:    ...  # never raises — returns degraded fact on failure
```

**`derived_from` auto-population:** `bb.post(fact, agent)` sets `fact.derived_from = agent.reads`. Agents do not bookkeep lineage manually.

**`skipped.*` semantics for `DecisionAggregator`:**
- `reason == PROVABLY_PASS` or `GUARD_FIRED` → treat the corresponding verdict as **PASS**
- `reason == GATE_BLOCKED` → claim already blocked; verdict is not applicable
- `reason == TIMEOUT` → treat as degraded missing fact; lower confidence, add manual-review note

**`GateGatedAgent` mixin** — all agents downstream of `DocGate` inherit this:
```python
class GateGatedAgent(Agent):
    def ready(self, bb) -> AgentState:
        if bb.has("gate.blocked"):  return AgentState.SKIP   # reason → GATE_BLOCKED
        if not bb.has("gate.passed"): return AgentState.WAIT
        return self._ready(bb)      # agent checks its own additional inputs
    def skip_reason(self, bb) -> str:
        return "GATE_BLOCKED" if bb.has("gate.blocked") else "PROVABLY_PASS"
    def _ready(self, bb) -> AgentState: ...  # override per agent
```

### 7.4 Frontend — the board IS the UI
Single unified Next.js view. No login, no role switching. Shows: claim submission form → live blackboard (facts light up as SSE events arrive; agents step through `idle → watching → running → posted`) → final decision with full deduction breakdown. Early verdicts pop before the claim fully resolves. This is the real-time edge (§3.2 #4).

### 7.6 Honest tradeoff
Concurrent agents finish in nondeterministic **order** → trace interleaving varies run-to-run. The **decision, amount, and fact-set are deterministic**; only ordering differs. Sort by `seq` for a canonical view; eval asserts on the fact set + decision, not interleaving. (B-static's no-re-firing rule is what keeps even this bounded — there are no cascade loops.)

### 7.9 Fallback — Architecture A (phased pipeline)
Same agents, same component contracts, same DB facts — but orchestrated as a fixed phase sequence (`intake → detect → extract → gate → synthesize → rules → financial → decide → verify`) with `asyncio.gather` fan-outs *within* a phase and barriers *between*. Loses the instant-verdict property and the per-agent speed/confidence tuning, but is simpler to land. **Only used if the blackboard scheduler proves unstable in the build window.** The contracts are identical, so the switch costs little.

---

## 8. Why B-static (decision rationale — keep for the technical review)

### 8.1 Goal 1 — fastest response
Early-terminal cases (TC005/07/08/09/12) get a real verdict the instant their evidence exists — TC008/TC009 at `t≈0` — instead of after a full pipeline. The happy path (TC004/10) is bounded by extraction either way (a tie). B-static is faster on ~5/12 cases and **never slower**.

### 8.2 Goal 2 — highest confidence, *without* losing speed
The speed↔confidence tension is **not uniform across checks**:
- Per-claim limit reads the submitted amount → needs **zero** extraction confidence → fire instantly.
- Exclusion (TC006: misreading "Teeth Whitening" mis-pays ₹4,000) → **exquisitely** confidence-sensitive → wait for the self-corrected, high-confidence extraction.

A phased design forces **one global choice** for the whole claim. B-static lets **each agent set its own tolerance** — instant checks fire immediately, confidence-sensitive checks gate on the corrected fact. Both goals satisfied at once, because they apply to different checks. **This is the property the reference's barriered DAG cannot express**, and it's the core of our System-Design argument.

### 8.3 Against the grading rubric

| Criterion | Weight | B-static |
|-----------|--------|----------|
| System Design (+ multi-agent bonus) | 30% | **Strongest** — true concurrency + per-agent tuning + extend-live = drop in an agent |
| Engineering Quality | 25% | Safe **because** we dropped re-firing (no cascade loops); ~40-line scheduler; tests per component |
| Observability | 20% | Board-as-trace; every fact carries `derived_from` + policy refs; canonical `seq` ordering |
| AI Integration | 15% | Clinical-coherence synthesis (edge #2) + structured, self-correcting, validated extraction |
| Document Verification | 10% | Collect-all gate (edge #1) |

### 8.4 Why not full B (with re-firing)
Re-firing lets a late discovery retroactively re-trigger upstream agents — elegant, but it introduces nondeterminism, loop risk, and the hardest control flow to test. We already capture ~that benefit via extraction's internal self-correction + the verifier escalating to MANUAL_REVIEW. For a 2–3 day graded build that must be explainable, re-firing is a deliberate, documented cut.

---

## 9. Decisions Log (all locked)

- [x] **Architecture** → B-static. Fallback: Architecture A.
- [x] **Gemini model tier** → Flash everywhere (uniform across all agent roles).
- [x] **Verifier scope** → APPROVED and PARTIAL only. Skipped via guard on all other outcomes.
- [x] **`ready()` contract** → tri-state `AgentState` (WAIT/READY/SKIP). Scheduler posts skip facts. Explicit `reason` enum: `PROVABLY_PASS | GATE_BLOCKED | GUARD_FIRED | TIMEOUT`.
- [x] **`financial_facts`** → `FinancialReconciler` posts reconciled lines + bill_total + divergence flag. `FinancialCalculator` reads it and posts `financial_breakdown`.
- [x] **Blackboard watchdog** → per-claim wall-clock timeout (120 s default). Remaining pending agents drained as degraded TIMEOUT facts.
- [x] **SSE event schema** → full fact payload per event (§6.7). Redis channel: `claims:{claim_id}`.
- [x] **`seq` assignment** → per-claim atomic counter, assigned by `bb.post()` before DB persist.
- [x] **`derived_from`** → auto-populated from `agent.reads` by `bb.post()`.
- [x] **`ClinicalChainAgent`** → 3 checks: patient consistency, date ordering, test-bill alignment (§7.1).
- [x] **Extraction cache** → SHA-256 of file bytes → ExtractionResult, TTL 24 h (§6.9).
- [x] **Eval isolation** → in-memory ledger seeded from `claims_history` per test case (§6.10).
- [x] **API endpoints** → `POST /claims`, `GET /claims/{id}`, `GET /claims/{id}/stream` (§6.8).
- [x] **Document binning** → pages classified by type, consecutive same-type pages binned into one segment (§6.6).
- [x] **Name resolution** → token overlap first; LLM fallback on failure (§7.1).
- [x] **Confidence threshold** → 0.70 hardcoded (§6.11).
- [x] **API → Worker handoff** → `asyncio.BackgroundTasks` inside the FastAPI process. No separate Worker service. `POST /claims` registers `adjudicate(claim_id)` as a background task and returns immediately.
- [x] **CORS** → `CORSMiddleware` on FastAPI. Allow Vercel origin in prod, `*` in local dev. Required for browser → Render direct calls.
- [x] **Docker Compose services** → 5 services for local dev (API, Frontend, Redis, PostgreSQL, MinIO). No separate Worker. Prod uses Render + Vercel + Supabase + Upstash — all free tiers.
- [x] **Frontend** → Next.js 15 (App Router). SSE via `EventSource` unchanged.
- [x] **Database (prod)** → Supabase PostgreSQL (free 500 MB). Use direct connection URL (not pooler) for SQLAlchemy async. Alembic unchanged.
- [x] **Redis (prod)** → Upstash Redis (serverless, free). Pub/sub + cache API unchanged.
- [x] **File storage (prod)** → Supabase Storage (S3-compatible, free 1 GB). Same platform as DB. `stored_path` stays a bucket key; swap endpoint config only.
- [x] **Supabase connection caveat** → always use the direct connection string (`postgresql+asyncpg://...`), not the PgBouncer pooler URL. Pooler drops prepared statements that SQLAlchemy relies on.
- [x] **Backend deploy** → Render free web service (FastAPI + SSE) + Render background worker. Vercel excluded — serverless functions can't hold SSE connections or run background tasks.
- [x] **Frontend deploy** → Vercel hobby (free). Auto-deploys from GitHub.
- [x] **Render sleep caveat** → free tier sleeps after 15 min idle; hit the URL once before demoing.
- [x] **Vercel SSE constraint** → Vercel Hobby times out serverless functions at 10 s. `EventSource` and all `fetch` calls in the Next.js frontend must point directly at the Render backend URL (e.g. `https://your-app.onrender.com`). No SSE or API proxying through Next.js API routes (`/api/*`).
- [x] **`audit_log`** → dropped. `facts` table is the sole audit trail.
- [x] **Policy versioning** → version-stamp-in-trace only. `policy_version_id` FK on every fact.
- [x] **Auth** → none for the demo. Endpoints are open.
- [x] **Frontend views** → single unified view, no auth, no role switching.
- [x] **Test-fixture strategy** → synthetic docs + real vision for a few cases; content-injection for the full eval suite (PRD §8.4).

---

*Architecture locked at rev 9. All gaps resolved — no open decisions remain. Zero-cost deployment stack confirmed (Render + Vercel + Supabase + Upstash). Rule logic lives in `PRD.md`; visuals in `DIAGRAMS.md`. Ready to build — Day 1 target is all 12 cases passing on a running system.*
