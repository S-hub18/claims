<div align="center">

# ⚡ ClaimStream

### AI-Native OPD Claims Adjudication Engine

*A production-grade, multi-agent system that reads medical documents, reasons over policy, detects fraud, and explains every decision — end to end, in seconds.*

<br/>

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Vercel-black?style=for-the-badge&logo=vercel)](https://claims-d3b9z5cr2-soumyas-projects-2c6754d6.vercel.app)
[![API](https://img.shields.io/badge/Backend%20API-Render-46E3B7?style=for-the-badge&logo=render)](https://claims-w2ze.onrender.com/health)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?style=for-the-badge&logo=next.js)](https://nextjs.org)
[![Claude](https://img.shields.io/badge/Claude-Haiku-D97757?style=for-the-badge&logo=anthropic&logoColor=white)](https://anthropic.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)

</div>

---

## The Problem

Every OPD claim today goes through a human reviewer. They check the documents, read the policy, apply financial rules, look for fraud signals, and write a decision. It's slow, inconsistent, and doesn't scale.

ClaimStream automates that entire pipeline — not with a monolithic model, but with a coordinated swarm of specialised agents that each own one part of the problem. The result is a system that's faster than any human reviewer, more consistent, and — critically — **explainable**.

---

## What Happens When a Claim Is Submitted

```
Employee submits claim
  → uploads prescription + hospital bill
  → enters treatment type, amount, date

                    ┌──────────────────────────────┐
                    │       BLACKBOARD ENGINE       │
                    │                               │
  Wave 1 ─────────▶│  MemberResolver               │ Who is this member?
  (parallel)        │  IntakeValidator              │ Are the fields valid?
                    │  DocExtractor × N  ←─ Claude  │ Read every document
                    │                               │
  Wave 2 ─────────▶│  DocGate                      │ Right document types?
                    │                               │ ← BLOCKS here if not
  Wave 3 ─────────▶│  SemanticMapper               │ Unify extracted fields
                    │  CrossValidation              │ Same patient across docs?
                    │  PrescriptionCheck            │ Diagnosis backed up?
                    │                               │
  Wave 4 ─────────▶│  ExclusionAgent               │ Policy exclusions?
  (parallel)        │  FinancialReconciler          │ Co-pay, sub-limit, network
                    │  WaitingPeriodAgent           │ Waiting periods?
                    │  PreAuthAgent                 │ Pre-auth required?
                    │  VelocityFraudAgent           │ Too many claims today?
                    │  DocumentFraudAgent           │ Anomaly signals?
                    │                               │
  Wave 5 ─────────▶│  PolicyReasonerAgent ←─ LangGraph + LLM │
                    │                               │ Verify exclusion verdict
                    │  FinancialCalculator          │ Final waterfall payout
                    │                               │
                    └──────────────┬────────────────┘
                                   │
                            Aggregator
                                   │
                    ┌──────────────▼────────────────┐
                    │  APPROVED · PARTIAL            │
                    │  REJECTED · MANUAL_REVIEW      │
                    │                               │
                    │  + approved amount            │
                    │  + confidence score           │
                    │  + full replayable trace      │
                    └───────────────────────────────┘
```

---

## Architecture Deep Dive

### The Blackboard Pattern

At the core is a **B-static blackboard** — an append-only, immutable fact store. Agents don't talk to each other. They declare what they `read` and what they `write`. The scheduler fires each agent the instant its inputs appear on the board — parallelism is automatic, not choreographed.

```python
# Every agent declares its contract
class WaitingPeriodAgent(GateGatedAgent):
    reads  = ["submission", "member"]
    writes = "verdict.waiting"

    async def _run(self, bb: Blackboard) -> Fact:
        member = bb.get("member").value
        # ... apply waiting period rules from policy
        return Fact(key=self.writes, value={"status": "REJECTED", ...})
```

The scheduler loop is ~50 lines:

```
while agents are pending or running:
    for each pending agent:
        state = agent.ready(blackboard)   # WAIT | READY | SKIP
        if READY → fire as asyncio.Task   # runs concurrently
        if SKIP  → prune (post skipped fact with reason)
    await first completed task
    post result → may unblock more agents
```

No phases. No barriers. No coordinator deciding who goes next.

---

### LangGraph: Policy Reasoning

The most nuanced part of adjudication is coverage reasoning — whether a diagnosis is truly excluded or just keyword-matched. A keyword match for "diabetes" might be a routine consultation, not a pre-existing condition claim. This is where **LangGraph** comes in.

```
                ┌─────────────────────────────────────────────┐
                │         PolicyReasonerAgent StateGraph       │
                │                                             │
 ExclusionAgent │  load_context                               │
 posts          │       │                                     │
 coverage  ────▶│       ▼                                     │
 (keyword)      │  identify_ambiguity                         │
                │       │                                     │
                │  ┌────▼─────────────────────────────────┐  │
                │  │         verify_exclusions             │  │
                │  │  LLM calls verify_exclusion tool      │  │
                │  │  and lookup_policy_clause tool        │  │
                │  │  (up to MAX_ITERS=3 reasoning passes) │  │
                │  └────┬──────────────────────────────────┘  │
                │       │                                     │
                │  ┌────▼────┐  ┌─────────┐  ┌──────────┐   │
                │  │ CONFIRM │  │OVERRIDE │  │ ESCALATE │   │
                │  │ keyword │  │post new │  │ post     │   │
                │  │ stands  │  │coverage │  │ ambiguity│   │
                │  └─────────┘  └─────────┘  └──────────┘   │
                └─────────────────────────────────────────────┘
```

Three outcomes:
- **CONFIRM** — LangGraph agrees with the keyword verdict; no new fact posted
- **OVERRIDE** — LangGraph finds the keyword was wrong; posts `coverage.revised` which downstream agents use instead
- **ESCALATE** — genuinely ambiguous after 3 passes; posts `flag.ambiguity` → `MANUAL_REVIEW`

The keyword-based answer is posted immediately (< 0.6s) so the client sees a fast preliminary decision while LangGraph reasons in the background.

---

### Claude Vision: Document Extraction

Every uploaded document (PDF or image) passes through Claude Haiku with **forced tool-use** — the model is given a `record_extraction` tool and must call it. No free-text parsing, no regex, no prompt engineering fragility.

```
  Uploaded PDF/image
        │
        ▼
  ┌─────────────────────────────────────────┐
  │          AnthropicClient.extract()      │
  │                                         │
  │  1. First pass (temp=0.1)               │
  │     → record_extraction tool call       │
  │     → structured ExtractionResult       │
  │                                         │
  │  2. If confidence < threshold:          │
  │     → targeted re-read                  │
  │     → keep higher-confidence result     │
  │                                         │
  │  3. If document has amounts:            │
  │     → second pass (temp=0.6)            │
  │     → compare totals                    │
  │     → disagree? → UNREADABLE            │
  │       (hallucination guard)             │
  └─────────────────────────────────────────┘
        │
        ▼
  ExtractionResult {
    patient_name, doctor_name, diagnosis,
    line_items, total_amount, confidence,
    readable, quality
  }
```

**Combined PDF splitting** — a single uploaded PDF that contains multiple documents (prescription + bill + lab report stitched together) is handled in one segmentation pass. Claude identifies each document, its type, and its page span. Continuation pages (a multi-page bill) are grouped into one entry.

---

### Confidence Model

Every decision carries a confidence score that's computed from real signals — not vibes.

```
confidence = 0.95 × min(avg_extraction_quality, avg_rule_certainty)
           − 0.25 × number_of_degraded_components
```

| Scenario | Confidence |
|---|---|
| Clean approval, all docs clear | ~0.95 |
| One document low-quality | ~0.75 |
| Component failure (graceful degradation) | ~0.70 |
| Multiple issues | < 0.60 → MANUAL_REVIEW |

---

## Agent Roster

| Agent | Wave | Reads | Writes | Responsibility |
|---|---|---|---|---|
| `MemberResolver` | 1 | submission | member | Resolve member identity against policy roster |
| `IntakeValidator` | 1 | submission | intake | Validate required fields, dates, amounts |
| `DocExtractor` × N | 1 | submission | extraction.{id} | Claude vision extraction per document |
| `DocGate` | 2 | submission, member | gate | Verify correct document types; block early if not |
| `SemanticMapper` | 3 | gate, extraction.* | semantic | Unify all extracted fields into one claim view |
| `CrossValidation` | 3 | semantic | verdict.cross | Patient name + date consistency across documents |
| `PrescriptionCorroboration` | 3 | semantic | verdict.presc | Prescription supports the diagnosed treatment |
| `ExclusionAgent` | 4 | semantic | coverage | Keyword-based policy exclusion check |
| `FinancialReconciler` | 4 | semantic | coverage | Co-pay, sub-limit, network discount application |
| `WaitingPeriodAgent` | 4 | submission, member | verdict.waiting | Condition-specific waiting period enforcement |
| `PreAuthAgent` | 4 | submission, member | verdict.preauth | Pre-authorisation requirement enforcement |
| `VelocityFraudAgent` | 4 | submission | verdict.velocity | Same-day / monthly claim frequency |
| `DocumentFraudAgent` | 4 | submission | verdict.docfraud | Anomaly signals; injectable fault hook |
| `PolicyReasonerAgent` | 5 | coverage | coverage.revised | LangGraph reasoning over exclusion verdict |
| `FinancialCalculator` | 5 | coverage | financial | Final payout waterfall |

Agents that will never be needed self-declare `SKIP` — they appear in the trace as **short-circuited**, not absent, so the audit log is always complete.

---

## Three Views

<table>
<tr>
<td width="33%" valign="top">

### 🎭 Demo Profiles
10 pre-loaded employees from Supabase, each representing a distinct scenario. Run any of the 12 test cases against the live engine and see the real decision with timing.

</td>
<td width="33%" valign="top">

### 🛠 Custom Claim
Build a claim from scratch. Upload real PDFs — Claude extracts them. Edit the policy inline (limits, co-pays, pre-auth). Trigger real-time velocity fraud. Simulate a component failure.

</td>
<td width="33%" valign="top">

### 🔬 Eval Suite
Lifecycle inspector. Runs any profile with a full blackboard trace. **Graph view** shows the fork-join wave structure. **Timeline view** shows per-step timing and confidence.

</td>
</tr>
</table>

---

## 12 Test Cases

| ID | Scenario | Expected | What It Tests |
|---|---|---|---|
| TC001 | Wrong document uploaded | BLOCKED | DocGate early rejection |
| TC002 | Unreadable document | BLOCKED | LLM quality guard |
| TC003 | Documents from different patients | BLOCKED | CrossValidation |
| TC004 | Clean consultation | **APPROVED** | Happy path, full waterfall |
| TC005 | Waiting period — diabetes | REJECTED | Member join date check |
| TC006 | Dental — partial cosmetic exclusion | **PARTIAL** | Exclusion + partial approval |
| TC007 | MRI without pre-authorisation | REJECTED | PreAuth enforcement |
| TC008 | Per-claim limit exceeded | REJECTED | Financial cap |
| TC009 | Multiple same-day claims | MANUAL_REVIEW | Velocity fraud signal |
| TC010 | Network hospital discount | **APPROVED** | Network discount applied |
| TC011 | Component failure mid-run | **APPROVED** | Graceful degradation |
| TC012 | Excluded treatment (bariatric) | REJECTED | Policy exclusion |

---

## Policy Configuration

All rules live in `assignment/policy_terms.json`. Zero hardcoding.

```
Sum insured (per employee)   ₹5,00,000
Annual OPD limit             ₹50,000
Per-claim limit              ₹5,000
Family floater               ₹1,50,000 combined

OPD Categories               Consultation · Diagnostic · Pharmacy
                             Dental · Vision · Alternative Medicine

Network Hospitals            Apollo · Fortis · Max · Manipal · Narayana
                             Medanta · Kokilaben · Aster · Columbia Asia · Sakra

Fraud Thresholds             Same-day limit: 2 claims
                             Monthly limit:  6 claims
                             Auto-review above: ₹25,000
```

---

## Tech Stack

```
Frontend          Next.js 14 (App Router) · TypeScript · Supabase JS
Backend           FastAPI · Python 3.12 · asyncio · uv
Agent Engine      Custom B-static blackboard scheduler
AI / LLM          Anthropic Claude Haiku (vision extraction)
                  LangGraph StateGraph (policy reasoning)
Database          Supabase (Postgres) — employee roster + documents
Deploy            Vercel (frontend) · Render (backend)
```

---

## Local Setup

**Prerequisites:** Python 3.12+, Node 18+, [`uv`](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/S-hub18/claims.git && cd claims
```

```bash
# Backend
cd backend
cp .env.example .env        # add ANTHROPIC_API_KEY
uv sync
uv run uvicorn app.api.main:app --reload --port 8000
```

```bash
# Frontend (new terminal)
cd frontend
cp .env.example .env.local  # add Supabase keys + NEXT_PUBLIC_API_URL=http://localhost:8000
npm install && npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

> No `ANTHROPIC_API_KEY`? The engine falls back to offline mode — all 10 demo profiles adjudicate correctly from inline content. Only real PDF uploads skip LLM extraction.

---

## Deploy

| | Backend | Frontend |
|---|---|---|
| **Platform** | Render (free) | Vercel (free) |
| **Config** | `render.yaml` at repo root | Set root dir to `frontend/` |
| **Key env var** | `ANTHROPIC_API_KEY`, `FRONTEND_URL` | `NEXT_PUBLIC_API_URL` |

> Render's free tier sleeps after 15 min of inactivity. Hit `/health` once before a demo to wake it (~30s cold start).

---

## Design Decisions

**Blackboard over DAG or LangGraph for the main engine.**  
A DAG requires you to wire execution order explicitly — add a new check and you're editing the graph. The blackboard derives order automatically from data dependencies. Add an agent, declare its `reads`, and it slots into the right wave. Parallelism is implicit, not configured.

LangGraph is used where it fits best: the policy reasoning sub-problem, which benefits from iterative tool calls, conditional branches, and multi-step chain-of-thought. It's the wrong tool for the outer loop.

**Forced tool-use over prompt-engineered extraction.**  
Free-text LLM output requires fragile parsing and degrades silently. Forced tool-use means the model either returns a valid typed object or nothing — and "nothing" is handled as `UNREADABLE`, not as a hallucination that flows into the financial calculation.

**B-static (each agent fires at most once).**  
Claims adjudication is a single-shot decision. B-static keeps the trace linear and fully replayable — every fact carries a sequence number and a `derived_from` lineage.

**In-memory store for the demo; pluggable for production.**  
`ClaimStore` already accepts an optional Redis client and DB session factory. Moving to distributed state is a config change, not a rewrite. The velocity ledger is keyed by `(client_session, member_id)` so concurrent evaluators stay isolated.

---

## Limitations & What Comes Next

| Current | At 10× load |
|---|---|
| In-memory claim store (per-process) | Redis pub/sub + Postgres persistence |
| Single uvicorn worker | Multiple workers; Redis-backed store |
| Velocity ledger is per-process | Redis `INCR` with TTL — atomic, cross-process |
| Multi-doc PDF uses one-pass extraction (no per-segment consistency guard) | pypdf page split + guarded `extract()` per segment |
| No API authentication | JWT middleware, per-tenant policy isolation |

---

<div align="center">

Built for the Plum AI Engineer Assignment · 2024

</div>
