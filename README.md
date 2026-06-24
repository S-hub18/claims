# ClaimStream — AI-Powered OPD Claims Adjudication

> Plum AI Engineer Assignment · Multi-agent health insurance claims processing with full explainability

**Live demo:** [claims-d3b9z5cr2-soumyas-projects-2c6754d6.vercel.app](https://claims-d3b9z5cr2-soumyas-projects-2c6754d6.vercel.app)  
**Backend API:** [claims-w2ze.onrender.com](https://claims-w2ze.onrender.com/health)

---

## What It Does

An employee submits a health insurance OPD claim — uploading a prescription, hospital bill, or lab report. Within seconds, a swarm of specialised agents reads the documents, validates them against the policy, checks for fraud, applies financial rules, and produces a decision: **APPROVED**, **PARTIAL**, **REJECTED**, or **MANUAL_REVIEW** — with a full, replayable trace of every step.

Every decision is explainable. Every failure is graceful.

---

## Architecture

### The Blackboard Pattern

The core of the system is a **B-static blackboard** — a shared, append-only fact store that agents read from and write to. No agent talks to another directly. No orchestrator decides who runs next. The scheduler fires each agent the instant its declared inputs appear on the board.

```
                        ┌─────────────────────────────────────────┐
                        │              BLACKBOARD                  │
                        │  (append-only, immutable fact store)     │
                        └──────────────┬──────────────────────────┘
                                       │
          ┌────────────────────────────┼─────────────────────────────┐
          │                            │                              │
   reads "submission"          reads "submission"           reads "submission"
          │                            │                              │
   ┌──────▼──────┐            ┌────────▼──────┐            ┌────────▼──────┐
   │  Member     │            │  Intake       │            │  DocExtractor │ × N docs
   │  Resolver   │            │  Validator    │            │  (Claude LLM) │
   └──────┬──────┘            └────────┬──────┘            └────────┬──────┘
   writes "member"            writes "intake"              writes "extraction.X"
          │                            │                              │
          └────────────────────────────┼─────────────────────────────┘
                                       │ reads "member" + "extraction.*"
                                ┌──────▼──────┐
                                │   DocGate   │  ← blocks if wrong docs uploaded
                                └──────┬──────┘
                                writes "gate"
                                       │
             ┌─────────────────────────┼──────────────────────────┐
             │                         │                           │
      reads "gate"               reads "gate"               reads "gate"
      + "extraction.*"           + "extraction.*"           + "extraction.*"
             │                         │                           │
     ┌───────▼───────┐         ┌───────▼───────┐         ┌───────▼───────┐
     │ SemanticMapper│         │ CrossValidat  │         │ Prescription  │
     └───────┬───────┘         │ ion           │         │ Corroboration │
     writes "semantic"         └───────────────┘         └───────────────┘
             │                 writes "verdict.cross"    writes "verdict.presc"
             │
     ┌───────┴─────────────────────────────────────────────┐
     │            reads "semantic" (parallel wave)          │
     │                                                      │
 ┌───▼──────┐ ┌──────────┐ ┌───────────┐ ┌────────────┐   │
 │Exclusion │ │Financial │ │ Waiting   │ │  PreAuth   │   │
 │Agent     │ │Reconciler│ │ Period    │ │  Agent     │   │
 └───┬──────┘ └────┬─────┘ └─────┬─────┘ └────┬───────┘   │
     │             │              │             │            │
 ┌───▼──────┐ ┌───▼──────┐ ┌────▼──────┐ ┌───▼───────┐   │
 │verdict.  │ │Financial │ │verdict.   │ │verdict.   │   │
 │exclusion │ │Calculator│ │waiting    │ │preauth    │   │
 └──────────┘ └────┬─────┘ └───────────┘ └───────────┘   │
                   │                                        │
              ┌────▼──────┐ ┌────────────┐ ┌─────────────┐ │
              │ PerClaim  │ │ Velocity   │ │  Document   │ │
              │ Limit     │ │ Fraud      │ │  Fraud      │ │
              └────┬──────┘ └─────┬──────┘ └──────┬──────┘ │
              verdict.       verdict.         verdict.       │
              perclaim       velocity         docfraud       │
     └────────────────────────────────────────────────────┘
                               │
                      ┌────────▼────────┐
                      │ PolicyReasoner  │  (deterministic keyword + optional LLM)
                      └────────┬────────┘
                      writes "coverage"
                               │
                      ┌────────▼────────┐
                      │   Aggregator    │  (post-quiescence, sees full fact-set)
                      └────────┬────────┘
                               │
                        APPROVED / PARTIAL
                        REJECTED / MANUAL_REVIEW
```

### Scheduler — No Phases, No Barriers

The scheduler is ~50 lines. It polls pending agents, fires the ready ones as concurrent `asyncio` tasks, and posts each result the instant it lands — which can make other agents ready immediately.

```
while pending or running:
    for each pending agent:
        state = agent.ready(blackboard)   # tri-state: WAIT | READY | SKIP
        if READY → launch as asyncio.Task
        if SKIP  → post skipped.{name} fact and prune
    await first completed task
    post result fact → may trigger newly-ready agents
```

Agents that will never be needed (e.g. `WaitingPeriodAgent` when the condition has no waiting period) self-declare **SKIP** and are pruned immediately — they appear in the trace as short-circuited, not absent.

### Agent Roster (14 agents)

| Agent | Reads | Writes | Role |
|---|---|---|---|
| `MemberResolver` | submission | member | Look up policy member, resolve identity |
| `IntakeValidator` | submission | intake | Validate required fields, dates, amounts |
| `DocGate` | submission, member | gate | Verify correct document types are present |
| `DocExtractor` × N | submission | extraction.{id} | Claude vision → structured fields per doc |
| `SemanticMapper` | submission | semantic | Unify extracted fields into claim facts |
| `CrossValidation` | semantic | verdict.cross | Patient name / date consistency across docs |
| `PrescriptionCorroboration` | semantic | verdict.presc | Prescription backs the diagnosed treatment |
| `ExclusionAgent` | semantic | coverage | Check policy exclusions (bariatric, cosmetic…) |
| `FinancialReconciler` | semantic | coverage | Apply co-pay, sub-limit, network discount |
| `FinancialCalculator` | coverage | financial | Waterfall: gross → deductions → approved |
| `WaitingPeriodAgent` | submission, member | verdict.waiting | Enforce condition-specific waiting periods |
| `PreAuthAgent` | submission, member | verdict.preauth | Enforce pre-authorisation requirements |
| `PerClaimLimitAgent` | coverage | verdict.perclaim | Hard cap per claim (category-aware) |
| `VelocityFraudAgent` | submission | verdict.velocity | Same-day / monthly claim frequency check |
| `DocumentFraudAgent` | submission | verdict.docfraud | Anomaly signals; injectable fault for resilience demo |
| `PolicyReasonerAgent` | coverage | coverage.revised | Keyword + optional LLM coverage reasoning |

### LLM Integration — Claude Vision

Document extraction uses **Claude Haiku** with forced tool-use (`record_extraction`) so output is always structured — the model either returns a valid typed object or nothing. Three anti-hallucination layers:

1. **Low-confidence re-read** — if confidence < threshold, re-extract with a targeted prompt focussed on patient name, date, and total
2. **Self-consistency guard** — money-bearing documents are re-extracted at higher temperature; if the two reads disagree on amounts, the document is marked `UNREADABLE` rather than trusting either
3. **Combined-PDF splitting** — a single uploaded PDF containing multiple documents (prescription + bill + lab report) is segmented in one pass via a `record_documents` tool call; continuation pages (a multi-page bill) are grouped into one entry; single-doc PDFs fall back to the guarded `extract()` path

### Confidence Model

```
confidence = BASE(0.95) × min(extraction_quality, rule_certainty)
           − PENALTY(0.25) × degraded_component_count
```

A clean approval clears 0.85. A component failure visibly lowers it — the claim still decides, but the confidence drop signals that human review is warranted.

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| **Backend** | FastAPI + Python 3.12 | Async-native, 202 on submit, clean DI |
| **Agent engine** | Custom blackboard scheduler | Implicit parallelism, full lineage, no framework lock-in |
| **LLM** | Anthropic Claude Haiku | Fast, cheap, vision-capable, forced structured tool-use |
| **Frontend** | Next.js 14 (App Router) | SSR + client components, Vercel-native deploy |
| **Database** | Supabase (Postgres) | Employee roster + documents, real-time capable |
| **Deps** | uv (backend) · npm (frontend) | Reproducible installs from lock files |
| **Deploy** | Render (backend) · Vercel (frontend) | Zero-ops, free tier |

---

## Three Views

### Demo Profiles
Ten real test employees from the Supabase roster, each representing a different scenario. Documents are pre-loaded; the adjudication runs live against the backend engine. Every profile declares an expected outcome so you can verify correctness at a glance.

### Custom Claim
Build a brand-new claim from scratch — a claimant the engine has never seen.

- **Upload real documents** — PDFs or images; Claude extracts structured fields, combined PDFs are split automatically
- **Edit the policy inline** — change per-claim limit, sub-limits, co-pay %, network discount, pre-auth toggles; the edit is sent as a `policy_override` on the claim
- **Velocity fraud** — real in-memory ledger per browser session; submit the same member ID multiple times and watch the claim cross APPROVED → MANUAL_REVIEW as the same-day limit trips
- **Simulate failure** — crashes the `DocumentFraudAgent` mid-run; the claim still decides, confidence drops, and a manual-review note is added

### Eval Suite (Lifecycle Inspector)
Runs any demo profile through the live engine and replays the full blackboard trace with per-step timing and confidence scores. Two views:

- **Graph** — fork-join wave diagram; agents that ran in parallel appear in the same band; skipped agents appear in a labelled "short-circuited" band
- **Timeline** — linear, per-step timing, fact values, pass/fail verdict per agent

---

## Test Cases

| ID | Scenario | Expected |
|---|---|---|
| TC001 | Wrong document uploaded | BLOCKED |
| TC002 | Unreadable document | BLOCKED |
| TC003 | Documents belong to different patients | BLOCKED |
| TC004 | Clean consultation — full approval | APPROVED |
| TC005 | Waiting period — diabetes | REJECTED |
| TC006 | Dental partial approval — cosmetic exclusion | PARTIAL |
| TC007 | MRI without pre-authorisation | REJECTED |
| TC008 | Per-claim limit exceeded | REJECTED |
| TC009 | Fraud signal — multiple same-day claims | MANUAL_REVIEW |
| TC010 | Network hospital — discount applied | APPROVED |
| TC011 | Component failure — graceful degradation | APPROVED |
| TC012 | Excluded treatment | REJECTED |

---

## Policy

All rules are read from `assignment/policy_terms.json` at startup — zero hardcoding.

| Rule | Value |
|---|---|
| Sum insured (per employee) | ₹5,00,000 |
| Annual OPD limit | ₹50,000 |
| Per-claim limit | ₹5,000 |
| Family floater | ₹1,50,000 combined |
| High-value auto-review threshold | ₹25,000 |
| Fraud: same-day claims limit | 2 |
| Fraud: monthly claims limit | 6 |
| Network hospitals | Apollo · Fortis · Max · Manipal · Narayana · Medanta · Kokilaben · Aster · Columbia Asia · Sakra |
| OPD categories | Consultation · Diagnostic · Pharmacy · Dental · Vision · Alternative medicine |

---

## Local Setup

**Prerequisites:** Python 3.12+, Node 18+, [`uv`](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/S-hub18/claims.git
cd claims
```

**Backend**
```bash
cd backend
cp .env.example .env          # add ANTHROPIC_API_KEY
uv sync
uv run uvicorn app.api.main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
cp .env.example .env.local    # add Supabase keys + NEXT_PUBLIC_API_URL
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

> Without `ANTHROPIC_API_KEY` the engine falls back to offline mode — all demo profiles adjudicate correctly from inline content; only real uploaded PDFs skip LLM extraction.

---

## Deploy

| Service | Platform | Config |
|---|---|---|
| Backend | Render (free) | `render.yaml` at repo root |
| Frontend | Vercel (free) | Set root directory to `frontend/` |

**Env vars:**

| Variable | Platform | Value |
|---|---|---|
| `ANTHROPIC_API_KEY` | Render | Your Anthropic key |
| `FRONTEND_URL` | Render | Your Vercel deployment URL (for CORS) |
| `NEXT_PUBLIC_API_URL` | Vercel | Your Render service URL |
| `NEXT_PUBLIC_SUPABASE_URL` | Vercel | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Vercel | Supabase anon key |

> Render's free tier sleeps after 15 min of inactivity — hit `/health` once before a demo to wake it (~30s cold start).

---

## Key Design Decisions

**Why a blackboard instead of a DAG or pipeline?**  
A DAG requires you to know the execution order upfront and wire it explicitly. The blackboard derives order automatically from data dependencies — add a new agent, declare its `reads`, and it slots into the right wave with zero coordination. Parallelism is implicit: any two agents whose inputs don't overlap run concurrently with no extra code.

**Why B-static (each agent fires at most once)?**  
Claims adjudication is a single-shot decision, not an iterative refinement. B-static keeps the trace linear and replayable — every fact has a sequence number and a `derived_from` lineage, so any decision can be reconstructed exactly from the log.

**Why forced tool-use for LLM extraction?**  
Free-text LLM output requires fragile parsing and degrades silently under prompt variation. Forced tool-use means the model either returns a valid structured object or nothing — and "nothing" is handled as `UNREADABLE`, not as a hallucination that propagates into the financial calculation.

**Why in-memory store for the demo?**  
Fast, simple, and sufficient for a single-process deploy. The `ClaimStore` already accepts an optional Redis client and DB session factory — adding persistence is a config change, not a rewrite.

---

## Limitations & Scale

| Limitation | Fix at 10× load |
|---|---|
| In-memory claim store (per-process) | Redis pub/sub + Postgres persistence |
| Single uvicorn worker | Multiple workers behind a load balancer |
| Velocity ledger is per-process | Redis `INCR` with TTL for atomic, cross-process counts |
| Per-segment consistency guard skipped for multi-doc PDFs | Split pages via pypdf; run guarded `extract()` per segment |
| No API authentication | JWT middleware; per-tenant policy isolation |
