# Backend Build Plan — Claims Processing System

> **Scope:** the FastAPI + blackboard backend only. Frontend has its own plan (`BUILD_PLAN_FRONTEND.md`).
> **Architecture reference:** `ARCHITECTURE.md` (rev 9, B-static blackboard — LOCKED).
> **Logic contract:** `PRD.md` (§4 rules, §5 precedence, §6 policy snapshot, §7 the 12 cases).
> **Last updated:** 2026-06-21
>
> **The one rule that governs build order:** the deterministic core (blackboard + agents + rules + decision)
> must go green on all 12 cases *before* a single line of web, SSE, real-vision, or deploy code is written.
> Everything below is ordered to hit that milestone first.

---

## 0. Milestones (what "done" means, in order)

| Milestone | Definition of done | Phases | Target |
|-----------|--------------------|--------|--------|
| **A — Green eval, offline** | `pytest tests/eval` passes all 12 cases by calling `adjudicate()` directly with content-injected docs. No web server, no real LLM, no Redis. | 0 · 1 · 2 · 4 · 6 | **End of Day 1** |
| **B — Live system** | `POST /claims` → background adjudication → facts persisted → SSE stream emits each fact → `GET /claims/{id}` returns full trace. Real Gemini vision on a few rendered docs. Deployed to Render. | 3 · 5 · 7 | **End of Day 2** |
| **C — Hardened + observable** | Graceful degradation proven (TC011), confidence model hits its targets (TC004 > 0.85, TC012 > 0.90), trace is demo-grade, §8.6 production scenarios stubbed, README + demo script. | 8 | **Day 3** |

**Critical path to Milestone A:** `0.1 → 1.* → 2.* → 4.* → 6.*`. The LLM layer (Phase 3) and web layer (Phase 5) are *deliberately not on this path* — content injection (PRD §8.4 option b) lets the full deterministic suite run with zero LLM calls.

---

## Phase 0 — Foundations & scaffold  *(Milestone A)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-0.1** | Repo + Python 3.12 project. `pyproject.toml` (uv or poetry). Package layout: `app/{blackboard,agents,rules,llm,db,api,policy,eval}/`. | — | `python -c "import app"` works; layout matches this plan. |
| **BE-0.2** | Dependency manifest. Core: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `redis`, `pydantic`, `pydantic-settings`, `python-multipart`, `tenacity`. LLM: `google-generativeai` (Gemini Flash, default adapter). Docs/vision: `pypdf`, `pdf2image`, `pillow`. Storage: `boto3` (Supabase S3 / MinIO). Test: `pytest`, `pytest-asyncio`, `httpx`, `respx`. | BE-0.1 | `uv sync` / `poetry install` clean. |
| **BE-0.3** | `Settings` (pydantic-settings) reads env: `DATABASE_URL`, `REDIS_URL`, `GEMINI_API_KEY`, `STORAGE_*`, `LLM_PROVIDER` (default `gemini`), `CONFIDENCE_THRESHOLD=0.70`, `CLAIM_TIMEOUT_S=120`, `CORS_ORIGINS`. `.env.example` committed. | BE-0.1 | Settings import with sane local defaults; secrets only from env. |
| **BE-0.4** | `docker-compose.yml` for local dev — 5 services: API, Postgres, Redis, MinIO, (frontend placeholder). **No separate worker** (ARCHITECTURE §5 — adjudication is an in-process `asyncio` background task). | BE-0.2 | `docker compose up` brings Postgres + Redis + MinIO healthy. |
| **BE-0.5** | `Makefile` / task runner: `make test`, `make eval`, `make run`, `make migrate`, `make lint`. Pre-commit: `ruff` + `ruff format`. | BE-0.1 | `make test` runs (empty pass). |

**Phase 0 exit:** empty app imports, deps installed, local infra up, one command runs tests.

---

## Phase 1 — Data & policy layer  *(Milestone A)*

> The DB is needed for the live system (Milestone B), but the **models** are defined now because the
> `Fact` shape is the contract the whole blackboard speaks. For Milestone A the eval runs against an
> in-memory blackboard; persistence is wired in Phase 5.

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-1.1** | SQLAlchemy async models (ARCHITECTURE §6.5): `facts` (claim_id, **seq**, key, author, value JSONB, confidence, derived_from[], degraded, tokens, duration, policy_version_id), `claims`, `claim_documents`, `claim_decisions`, `policy_versions` (id, loaded_at, content JSONB). **No `audit_log`** — facts table is the sole trail. | BE-0.3 | Models import; relationships resolve. |
| **BE-1.2** | Alembic init + first migration generating all tables. Targets Supabase **direct** connection string (not pooler — ARCHITECTURE §9 caveat). | BE-1.1 | `alembic upgrade head` on local Postgres creates all tables. |
| **BE-1.3** | Async DB session factory + dependency. Direct-connection DSN (`postgresql+asyncpg://`). | BE-1.2 | A test fixture opens a session and round-trips a row. |
| **BE-1.4** | **Policy loader** (ARCHITECTURE §6.5, PRD §2.1). `load_policy(path|bytes) -> Policy`: parses `policy_terms.json`, writes a `policy_versions` row, returns an accessor exposing **paths** (`policy.coverage.per_claim_limit`, `policy.opd_categories[cat].sub_limit`, `policy.waiting_periods.specific_conditions[cond]`, …). **Zero hardcoded values** — the loader is a generic reader of whatever JSON is injected. | BE-1.1 | Loading the sample policy exposes every key §6 cites; swapping in a mutated policy changes results with no code change. |
| **BE-1.5** | `Policy` accessor unit tests: every path PRD §4 references resolves; missing-key access raises a clear error (not silent `None`). | BE-1.4 | Tests green; a deliberately-truncated policy fails loudly. |

**Phase 1 exit:** policy is data (the engine reads keys, embeds nothing); schema migrates clean.

> **Anti-regression guard (the mistake we already caught once):** no rule module may contain a numeric
> literal that belongs in the policy. A lint check / grep in CI greps `app/rules` and `app/agents` for
> bare thresholds (`5000`, `0.10`, `90`, …) and fails the build. Policy is read at runtime, always.

---

## Phase 2 — Blackboard engine  *(Milestone A — the heart)*

> This is the ~40–50 line scheduler from ARCHITECTURE §7.3 plus the fact store and agent contract.
> It is small on purpose. Get it exactly right and every agent is trivial.

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-2.1** | `Fact` dataclass — fields exactly as the SSE schema (ARCHITECTURE §6.7): `claim_id, seq, key, author, value, confidence, degraded, derived_from, policy_version_id, reason`. Immutable. | BE-1.1 | Construct + serialize to the §6.7 JSON shape. |
| **BE-2.2** | `Blackboard` — append-only store. `post(fact, agent)` assigns a **per-claim atomic `seq`** before persist, auto-sets `derived_from = agent.reads` (ARCHITECTURE §7.3), fans out to `emit_sse` + `persist` hooks (both no-ops/in-memory for Milestone A). `has(key)`, `get(key)`, `all()`. | BE-2.1 | `seq` is monotonic per claim; `derived_from` auto-populated; two posts never collide on seq. |
| **BE-2.3** | `Agent` base + `AgentState` enum (`WAIT/READY/SKIP`). Contract: `name`, `reads: list[str]`, `ready(bb) -> AgentState`, `skip_reason(bb) -> str`, `async run(bb) -> Fact`. **`run` never raises** — wraps its body and returns a `degraded` fact on any exception. | BE-2.1 | A toy agent that raises still yields a degraded fact, not an exception. |
| **BE-2.4** | `GateGatedAgent` mixin (ARCHITECTURE §7.3) — `ready()` returns SKIP (`GATE_BLOCKED`) if `gate.blocked` present, WAIT until `gate.passed`, else delegates to `_ready()`. All post-gate agents inherit it. | BE-2.3 | Gated agent stays WAIT with no gate fact; SKIPs on `gate.blocked`; fires on `gate.passed`. |
| **BE-2.5** | **Scheduler** `adjudicate(submission, timeout_s=120)` exactly per ARCHITECTURE §7.3: poll `pending` for READY/SKIP, launch READY as tasks, `asyncio.wait(FIRST_COMPLETED)`, post results, drain on wall-clock timeout as degraded `TIMEOUT` facts. | BE-2.2, BE-2.3 | Runs a 3-agent toy DAG to completion; a hung agent is drained as degraded at the deadline. |
| **BE-2.6** | `skipped.*` semantics for the aggregator (ARCHITECTURE §7.3): `PROVABLY_PASS`/`GUARD_FIRED` → treat verdict as PASS; `GATE_BLOCKED` → N/A; `TIMEOUT` → degraded missing fact (lower confidence, manual-review note). Encode as a small resolver used by `DecisionAggregator`. | BE-2.5 | Unit test maps each reason to the right downstream treatment. |
| **BE-2.7** | Scheduler tests: ordering nondeterminism is bounded (decision + fact-set deterministic, only interleaving varies — ARCHITECTURE §7.6); no agent fires twice (B-static); SKIP prunes correctly. | BE-2.5 | 50 repeated runs → identical fact-set + decision, sorted by `seq`. |

**Phase 2 exit:** a generic, tested orchestrator that fires agents the instant their inputs exist, never re-fires, never crashes, and is deterministic on its output set.

---

## Phase 3 — LLM & extraction layer  *(Milestone B — off the critical path)*

> Provider-agnostic by design. ARCHITECTURE §5 locks **Gemini Flash** as the default; this layer makes
> Claude (or any model) a one-adapter swap, which also keeps the differentiation option open without a rewrite.

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-3.1** | `LLMClient` protocol: `classify_doc(image) -> DocType`, `extract(image, schema) -> dict[field → {value, confidence, source_text}]`, `compare_names(a, b) -> verdict`, `structured(prompt, schema) -> obj`. All return **structured output** (no free-text parsing). | BE-0.3 | Protocol defined; a fake in-memory client satisfies it for tests. |
| **BE-3.2** | `GeminiClient` implementing the protocol (`google-generativeai`, Flash, vision + JSON mode). Retries via `tenacity`; timeout → raise (caught by agent → degraded fact). | BE-3.1 | Live call extracts fields from a rendered sample doc. |
| **BE-3.3** | `FakeLLMClient` for tests/eval — returns canned structured results keyed by fixture. Lets the full suite run with **zero** network. | BE-3.1 | Eval (Phase 6) runs offline through this client. |
| **BE-3.4** | **Extraction cache** (ARCHITECTURE §6.9): key `sha256(file_bytes)`, value serialized `ExtractionResult`, TTL 24 h, Redis-backed (in-memory dict for Milestone A). Cache hit → skip the model call. Category-agnostic. | BE-3.1, BE-2.2 | Same bytes twice → one model call; cache hit returns identical result. |
| **BE-3.5** | **Document binning** (ARCHITECTURE §6.6): `DocDetector` classifies each PDF page, bins consecutive same-type pages into one `segment.*` fact; single images → one segment. | BE-3.1 | The §6.6 example (`[Rx,Rx,Bill]` → 2 segments) bins correctly. |
| **BE-3.6** | **Self-correction** (PRD §4.2): a load-bearing field (per §4.13) null/low-confidence on a *readable* doc → re-read once, keep higher confidence, post the corrected result (B-static: corrected *before* posting, no re-fire). | BE-3.2 | A seeded low-confidence field triggers exactly one re-read and the better value is posted. |

**Phase 3 exit:** messy docs read into structured, confidence-tagged facts; model swappable; cached; self-correcting before post.

---

## Phase 4 — Agents & deterministic rules  *(Milestone A — the bulk)*

> Each agent is small: declare `reads`, implement `ready()` and `run()`, post one fact. **LLM proposes,
> deterministic code decides** (ARCHITECTURE principle 2): agents that need extraction call the `LLMClient`;
> every verdict and every rupee is deterministic Python (`decimal.Decimal`). All thresholds via the Phase-1
> policy accessor. Build in dependency order so the eval can be turned on incrementally.

### 4a — Intake / instant agents (fire at t≈0, no documents)

| ID | Agent | Reads → Writes | Logic source | Proves |
|----|-------|----------------|--------------|--------|
| **BE-4.1** | `MemberResolver` | `submission` → `member` | PRD §4.1 | roster lookup; missing → STOP fact |
| **BE-4.2** | `IntakeValidator` | `submission` → `intake` (or STOP) | PRD §4.1 | min-amount; deadline **disabled** for eval (§8.3) |
| **BE-4.3** | `PerClaimLimitAgent` | `submission` → `verdict.limits.per_claim` | PRD §4.8 (`binding_ceiling = max(per_claim_limit, sub_limit)`) | **TC008** reject vs **TC006** cap |
| **BE-4.4** | `HighValueAgent` | `submission` → `verdict.fraud.high_value` | PRD §4.9 (`auto_manual_review_above`) | high-value FLAG |
| **BE-4.5** | `VelocityFraudAgent` | `submission`,`member` → `verdict.fraud.velocity` | PRD §4.9 Track 1 + ledger | **TC009** 4th same-day |

### 4b — Document pipeline

| ID | Agent | Reads → Writes | Logic source | Proves |
|----|-------|----------------|--------------|--------|
| **BE-4.6** | `DocDetector` | `documents` → `segment.*` | ARCHITECTURE §6.6 | binning |
| **BE-4.7** | `Extractor` (per segment) | `segment.*` → `extraction.{id}` | PRD §4.2 | structured, self-correcting extraction |
| **BE-4.8** | **`DocGate`** (collect-all) | all `segment.*`+`extraction.*` → `gate.passed` \| `gate.blocked` | PRD §4.3 (**edge #1**) | **TC001/002/003** — *all* problems in one message; dependency rule (unreadable ⇒ skip type/patient for that doc) |

### 4c — Synthesis facts (post-gate, fire as extraction lands)

| ID | Agent | Reads → Writes | Logic source | Proves |
|----|-------|----------------|--------------|--------|
| **BE-4.9** | `SemanticMapper` | `extraction.*` → `semantic_map` | PRD §4.4 | diagnosis→condition, treatment→exclusion, high-value test detect |
| **BE-4.10** | `PatientResolver` | `extraction.*` → `patient_identity` | PRD §8.5 + ARCHITECTURE §7.1 (token-overlap → LLM fallback) | member OR dependent match |
| **BE-4.11** | `FinancialReconciler` | `extraction.*` → `financial_facts` (lines, bill_total, line_sum, divergence_flagged) | PRD §4.10 step 2, ARCHITECTURE §6.3 | Σlines vs bill_total reconcile |
| **BE-4.12** | **`ClinicalChainAgent`** | `extraction.*` → `clinical_chain` (coherence_score, signals) | ARCHITECTURE §7.1 (**edge #2**) | patient consistency · date ordering · test↔bill alignment |

### 4d — Policy rule agents (gate-gated; carry adaptive guards)

| ID | Agent | Reads → Writes | Logic source | Proves |
|----|-------|----------------|--------------|--------|
| **BE-4.13** | `WaitingPeriodAgent` | `member`,`semantic_map` → `verdict.waiting_period` | PRD §4.5 | **TC005** (44 < 90 diabetes); **guard:** SKIP when provably PASS |
| **BE-4.14** | `ExclusionAgent` | `semantic_map`,`clinical_chain` → `verdict.exclusion` | PRD §4.6 | **TC012** whole-claim vs **TC006** line-item |
| **BE-4.15** | `PreAuthAgent` | `financial_facts`,`semantic_map` → `verdict.pre_auth` | PRD §4.7 | **TC007** MRI > threshold; **guard:** SKIP on non-diagnostic |
| **BE-4.16** | `AggregateLimitsAgent` | `financial_facts`,`member` → `verdict.limits.aggregate` | PRD §4.8 (annual OPD, sum insured, alt-med sessions) | not eval-binding; completeness |
| **BE-4.17** | `DocumentFraudAgent` | `patient_identity`,`clinical_chain` → `verdict.fraud.document` | PRD §4.9 Track 2 | doc-anomaly FLAG |

### 4e — Calculation & decision

| ID | Agent | Reads → Writes | Logic source | Proves |
|----|-------|----------------|--------------|--------|
| **BE-4.18** | `FinancialCalculator` | `financial_facts`+all `verdict.*` → `financial_breakdown` | PRD §4.10 (**discount → copay → cap**, all `Decimal`); schema ARCHITECTURE §6.3 | **TC004 ₹1,350 · TC010 ₹3,240 · TC006 ₹8,000 · TC011 ₹4,000** |
| **BE-4.19** | `DecisionAggregator` | all `verdict.*`+`financial_breakdown`+`skipped.*` → `decision` | PRD §5 precedence; confidence §4.13 | full precedence ladder; **TC011** degraded-but-APPROVED |
| **BE-4.20** | `Verifier` (async) | `decision`+`extraction.*` → `verifier_result` | PRD §4.12; ARCHITECTURE §6.2 | runs only on APPROVED/PARTIAL; **guard:** SKIP on REJECTED/BLOCKED/MANUAL_REVIEW |

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-4.21** | `build_agents()` registry wiring all agents into the scheduler. | all 4a–4e | `adjudicate()` runs the full DAG on a fixture end-to-end. |
| **BE-4.22** | **Adaptive guards** as `ready()` predicates (ARCHITECTURE §3.3 / §7.1): `WaitingPeriodAgent`, `PreAuthAgent`, `Verifier` resolve to SKIP with the right `reason` enum instead of firing when provably unnecessary. | BE-4.13/15/20 | guard unit tests: each SKIPs on its provable-PASS condition, fires otherwise. |
| **BE-4.23** | **Confidence model** (PRD §4.13): component-based `f(extraction_quality, rule_certainty, completeness, verifier_agreement) − degradation_penalty`. | BE-4.19 | TC004 > 0.85, TC012 > 0.90, TC011 measurably lower than a clean approval. |
| **BE-4.24** | **Claims ledger** (PRD §4.9): deterministic store keyed by member/provider; velocity = indexed query. **Eval isolation** — per-case namespace seeded from `claims_history`/`ytd_claims_amount`, resets per case (ARCHITECTURE §6.10). | BE-4.5 | re-running the 12 cases never inflates velocity counts (TC009 stable across repeats). |

**Phase 4 exit:** every agent posts its fact; the full DAG runs; deterministic verdicts + rupees match PRD for all 12 cases (modulo the eval harness wiring in Phase 6).

---

## Phase 6 — Eval harness & tests  *(Milestone A — the proof)*

> Phase 5 (web/SSE) is intentionally *after* this. Milestone A is proven by calling `adjudicate()`
> directly. Numbered 6 to keep web=5 grouped with deploy.

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-6.1** | **Test-case loader** (PRD §8.4): ingest `test_cases.json`. TC001–003 carry `actual_type`/`quality`/`patient_name_on_doc` → exercise the gate. TC004–012 carry pre-extracted `content` → **content injection** (post `extraction.*` facts directly, bypassing vision). | BE-4.21 | all 12 load into submission + injected-fact form. |
| **BE-6.2** | **Eval runner** — for each case: fresh blackboard + isolated ledger, run `adjudicate()`, assert decision status + approved_amount + ranked reason_codes against expected. | BE-6.1, BE-4.24 | `make eval` runs all 12. |
| **BE-6.3** | **Turn the suite green**, case by case, in this order: gate cases (001–003) → simple approvals (004/010) → rule rejects (005/007/008/012) → partial (006) → fraud (009) → degraded (011). Fix logic, not tests. | BE-6.2 | **all 12 pass** ✅ — **Milestone A reached.** |
| **BE-6.4** | **Synthetic-vision proof** (PRD §8.4 option a): render 2–3 representative docs to images, run *real* Gemini extraction through them, assert the confidence metric is live (not injected). | BE-3.2, BE-6.3 | a real vision pass on rendered docs produces a plausible confidence within tolerance. |
| **BE-6.5** | **Component unit tests** (ARCHITECTURE principle 7): policy accessor, each rule, financial calc (decimal exactness), gate collect-all, scheduler, guards, confidence, ledger isolation. Target meaningful coverage on `rules/` + `blackboard/`. | Phase 2+4 | `make test` green; financial calc has explicit decimal-edge tests. |

**Phase 6 exit (Milestone A):** all 12 eval cases pass offline; components unit-tested; one real-vision case proves extraction is live.

---

## Phase 5 — API · SSE · persistence  *(Milestone B)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-5.1** | Wire `Blackboard.persist` hook to the DB (Phase 1) — every fact written as posted (ARCHITECTURE principle 5). | BE-2.2, BE-1.3 | after a run, the `facts` table holds the full trace sorted by `seq`. |
| **BE-5.2** | Redis pub/sub + `emit_sse` hook → channel `claims:{claim_id}`, full fact payload (ARCHITECTURE §6.7). Upstash in prod, local Redis in dev. | BE-2.2 | subscribing to a channel receives one message per posted fact. |
| **BE-5.3** | `POST /claims` — accept fields + multipart documents, store files (Supabase Storage / MinIO via boto3), create claim row, **register `adjudicate(claim_id)` as an `asyncio` BackgroundTask**, return `{claim_id}` immediately (ARCHITECTURE §6.8, §9). | BE-5.1 | returns in ms; adjudication proceeds in background; files land in the bucket. |
| **BE-5.4** | `GET /claims/{id}` — submission + current decision + all facts sorted by `seq`. | BE-5.1 | returns the full claim state. |
| **BE-5.5** | `GET /claims/{id}/stream` — SSE via `EventSource`, replays facts-so-far then live-tails the Redis channel, closes when the `decision` fact posts. | BE-5.2 | a client sees historical + live facts and a clean close. |
| **BE-5.6** | **CORS** middleware (ARCHITECTURE §5) — allow the Vercel origin in prod, `*` local. Without it the browser silently blocks every call. | BE-5.3 | a cross-origin browser fetch from the frontend succeeds. |
| **BE-5.7** | Never-500 envelope (ARCHITECTURE principle 6): any unhandled error in adjudication becomes a degraded `MANUAL_REVIEW` decision fact, not a crash. | BE-5.3 | a forced exception mid-run yields a degraded decision, HTTP stays clean. |

**Phase 5 exit:** the system runs as a service — submit returns instantly, facts persist + stream live, nothing 500s.

---

## Phase 7 — Deployment  *(Milestone B)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-7.1** | Supabase project: Postgres (direct connection DSN, **not** pooler), Storage bucket. Run `alembic upgrade head` against it. | BE-1.2 | tables live on Supabase; `stored_path` is a bucket key. |
| **BE-7.2** | Upstash Redis: set `REDIS_URL`; verify pub/sub + cache from a deployed dyno. | BE-5.2 | pub/sub works from Render. |
| **BE-7.3** | Render web service: FastAPI + SSE, `alembic upgrade head` on deploy, env wired, auto-deploy from GitHub. Note the **15-min idle sleep** — hit the URL before demoing. | BE-5.*, BE-7.1/2 | public URL serves `POST /claims` + live SSE. |
| **BE-7.4** | Smoke test against the deployed URL: submit a content-injected case, watch the SSE stream, confirm the decision. | BE-7.3 | a real claim adjudicates on the deployed backend. |

**Phase 7 exit (Milestone B):** deployed, public, streaming, green.

---

## Phase 8 — Hardening & observability  *(Milestone C)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **BE-8.1** | **Graceful-degradation proof** (PRD §4.14, TC011): inject a non-critical component failure → claim still APPROVED ₹4,000, failure visible in trace, confidence below clean, manual-review *note* (not status). | BE-4.19 | TC011 passes with the degraded-but-approved shape. |
| **BE-8.2** | **Trace quality**: every fact carries `derived_from` + policy refs + timing/tokens; `GET /claims/{id}` returns a demo-grade, replayable trace sorted by `seq`. | BE-5.4 | a reviewer can reconstruct *why* from the trace alone. |
| **BE-8.3** | **§8.6 production scenarios** stubbed + tested where cheap: policy in-force window, treatment-before-enrollment, all-lines-excluded → REJECTED, alt-med covered-system, category mismatch → MANUAL_REVIEW, pre-auth expired, zero-documents STOP, MANUAL_REVIEW provisional amount. | BE-4.* | each has a unit test; none regress the 12. |
| **BE-8.4** | **10x-load story** documented (not built): pointer to `FUTURE_DIRECTIONS.md` FD-1 (adaptive fraud), streaming feature store, graph ring-detection — the System-Design (30%) answer. | — | README "Scaling" section references FD-1. |
| **BE-8.5** | **README + demo script**: architecture summary, how to run eval, the 3 edges (collect-all gate, clinical coherence, true concurrency), the locked interpretation calls (per-claim × sub-limit). One-command local up. | all | a fresh clone runs the eval from the README. |
| **BE-8.6** | **Observability polish**: structured logging, per-agent timing surfaced, optional `/healthz`. | BE-5.3 | logs are greppable; health check returns 200. |

**Phase 8 exit (Milestone C):** demo-ready, observable, with the production-completeness and scaling story told.

---

## Build-order summary (the dependency spine)

```
0.1 scaffold
  └─► 1.1 models ─► 1.2 alembic ─► 1.3 session
        └─► 1.4 policy loader ──────────────────────┐  (policy-as-data; no hardcoding)
  └─► 2.1 Fact ─► 2.2 Blackboard ─► 2.3 Agent ─► 2.4 GateGated ─► 2.5 scheduler ─► 2.6/2.7 tests
        └─────────────────────────────► 4.1–4.20 agents (use policy + LLMClient)
                                              │  (3.* LLM layer feeds 4.7 Extractor; FakeLLM for eval)
                                              └─► 4.21 registry ─► 4.22 guards ─► 4.23 confidence ─► 4.24 ledger
                                                    └─► 6.1 loader ─► 6.2 runner ─► 6.3 GREEN (Milestone A) ─► 6.4 vision ─► 6.5 unit tests
                                                          └─► 5.1 persist ─► 5.2 SSE ─► 5.3 POST ─► 5.4 GET ─► 5.5 stream ─► 5.6 CORS ─► 5.7 never-500
                                                                └─► 7.1 Supabase ─► 7.2 Upstash ─► 7.3 Render ─► 7.4 smoke (Milestone B)
                                                                      └─► 8.* harden + observe + docs (Milestone C)
```

## Risk register & fallbacks

| Risk | Trigger | Fallback |
|------|---------|----------|
| Blackboard scheduler unstable | flaky ordering / deadlock in the build window | **Architecture A** (ARCHITECTURE §7.9) — same agents, same contracts, fixed phases + barriers. Switch is cheap; contracts identical. |
| Gemini vision quality on messy docs | low extraction confidence on rendered docs | self-correction re-read (BE-3.6); content-injection carries the deterministic suite regardless; swap `LLMClient` to Claude adapter. |
| Render cold-start at demo | 15-min idle sleep | hit the URL before demoing (BE-7.3); keep a warm-up ping. |
| Supabase prepared-statement errors | accidental pooler URL | always the **direct** DSN (BE-1.2 / §9 caveat). |
| Eval nondeterminism | ledger state bleed | per-case isolated namespace (BE-4.24); 50-run stability test (BE-2.7). |

## Open item carried from design

- **PRD change still pending your call:** promote *cross-document clinical coherence* (edge #2) from an §8.5 improvement bullet to a first-class stage in PRD §3 + a named check in §4. Backend already treats it as first-class (`ClinicalChainAgent`, BE-4.12), so this is a doc-alignment decision, not a build change.
