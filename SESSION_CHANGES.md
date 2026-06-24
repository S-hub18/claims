# Session changes — 2026-06-24

A running record of everything changed this session (eval/tester view, lifecycle
graph, editable policy, authentic fraud signals, cleanup). Newest first.

## Commits (origin/main)

| Commit | Summary |
|--------|---------|
| `5e270b9` | Authentic real-time velocity + simulate-failure toggle; drop seeded cases |
| `b76295e` | Remove Developer mode toggle and View full trace button |
| `449e515` | Custom claim: make the whole policy editable inline |
| `75e99d8` | Lifecycle graph: fork–join wave view of the multi-agent run |
| `cedaf74` | Add frontend `.env.example`, document `ANTHROPIC_API_KEY` in backend example |
| `d94ded0` | Add default `policy_terms.json` so the engine has its backup policy |
| `473bb7f` | Rebuild eval suite as a lifecycle inspector (tester view) |

## What changed, by area

### Fix: editable/uploaded policy 500 (uncommitted)
- Bug found during full Playwright sweep: submitting with a `policy_override` (every
  edited-policy or uploaded-`.json` custom run) crashed the POST with
  `KeyError: "policy path not found: 'members'"` → HTTP 500, which the browser reported
  as a CORS error. The server's default policy has a `members` list so it never tripped;
  an override policy has none, and `Policy.get("members")` raises (fail-loud by design).
- Fix: the claims route now uses the safe accessor `policy.members()` (defaults to `[]`)
  instead of `policy.get("members")`. One line in `backend/app/api/routes/claims.py`.
- Verified: override POST → 202 / GET → 200, and the override is genuinely applied
  (per-claim 500 ≥ sub-limit 400 on a ₹3,000 claim → REJECTED `PER_CLAIM_EXCEEDED`);
  in-browser editable-policy run adjudicates with no CORS/500.

### Combined / multi-document PDF splitting (uncommitted)
- Problem: one uploaded PDF that actually contains several documents (e.g. prescription
  + hospital bill + lab report stitched together) was treated as a single document.
- Added `segment()` to the Anthropic client: one Claude vision call over the whole PDF
  returns a list of documents via a `record_documents` tool — each with `doc_type`
  (the **7** confirmed types + UNKNOWN), 1-indexed `page_start`/`page_end`, and extracted
  fields. The prompt groups continuation pages (a doc spanning 2+ pages) into one entry.
  A single-document PDF defers to the guarded `extract()` so the hallucination checks
  still apply.
- Ingestion (`_expand_combined_pdfs` in the claims route) replaces each uploaded PDF with
  its constituent documents before adjudication, so each is gated/priced as its own
  document and the trace shows one extraction step per detected document. Inline-content
  (demo/test) documents are untouched.
- Verified with real Claude: `TC07_all.pdf` → 3 docs (PRESCRIPTION, LAB_REPORT,
  HOSPITAL_BILL); single `F012_prescription.pdf` → 1 doc. Offline/demo path unaffected.
- Trade-off (v1): multi-doc segments are extracted in the one segmentation pass, so the
  per-document re-extraction consistency guard isn't re-run per segment (single-doc PDFs
  still get it). A follow-up could split pages (pypdf) and run guarded extraction per
  segment.
- Files: `backend/app/llm/anthropic_client.py`, `backend/app/api/routes/claims.py`.


### Eval suite → "Lifecycle inspector / tester view" (`473bb7f`, `75e99d8`)
- Replaced the old hardcoded fake eval grid (always `pass: true`, fake timers) with a
  real tester view: runs the **selected demo profile** through the live engine and
  replays the **full blackboard trace** — every agent step, validated, with timing.
- Backend now returns the whole fact trace on `GET /claims/{id}`, with each fact stamped
  with cumulative per-step timing (`t_ms`). Non-serialisable fact values (uploaded-doc
  bytes, Decimals) are sanitised so the trace response never 500s.
- Two views behind a toggle:
  - **Graph** — a fork–join DAG built from each fact's `derived_from` lineage. Agents on
    the same wave ran in parallel; animated dispatch lines + pulsing junctions show the
    multi-agent concurrency; converges on the decision.
  - **Timeline** — linear, per-step timing + pass/fail verdicts.
- Skipped (gate-blocked) agents are grouped in a labelled "short-circuited" band instead
  of being orphaned into wave 0.
- Files: `backend/app/api/{schemas.py,store.py,routes/claims.py}`,
  `frontend/components/EvalView.tsx`, `frontend/lib/{api.ts,engine.ts,types.ts}`,
  `frontend/app/globals.css`.

### Editable policy in the Custom claim view (`449e515`)
- The whole policy panel is now inline-editable: the four top limits plus each OPD
  category's sub-limit, co-pay %, network-discount %, and a pre-auth toggle.
- Any edit clones the active policy, patches that path, and sends it as the claim's
  `policy_override` — so adjudication runs against the edited policy (no file upload).
- Added `document_requirements` to the frontend policy so an edited policy passes the
  backend's override validation (it was being silently rejected before).
- Styled as proper bordered fields (right-aligned numbers, focus ring) + reused toggle
  switch — replaced the earlier wobbly dashed inputs.
- Files: `frontend/components/PolicyPanel.tsx`, `frontend/lib/{engine.ts,types.ts,policy.ts}`,
  `frontend/app/globals.css`.

### Authentic real-time velocity fraud (`5e270b9`)
- Velocity is no longer seeded — a real in-memory **claims ledger** accumulates from
  actual submissions. Repeated claims for the same off-roster member trip the same-day /
  monthly limit on their own.
- Ledger is keyed by **`client_session : member_id`** so concurrent evaluators are
  isolated; a fresh tab/reload starts clean. Roster (demo) members never touch the
  ledger, so the graded cases stay deterministic.
- Files: `backend/app/api/{store.py,schemas.py,routes/claims.py}`, `frontend/lib/api.ts`.

### "Simulate a component failure" toggle (`5e270b9`)
- Transparent toggle in the Custom claim view that injects a fault (document-fraud agent
  crashes) so graceful degradation is demonstrable on demand: the claim still decides,
  confidence drops (~0.95 → ~0.70), and a manual-review note is added.
- Files: `frontend/components/CustomView.tsx`, `frontend/lib/{engine.ts,api.ts}`.

### Removed seeded/hardcoded-looking demo cases (Supabase — live DB)
- Deleted **TC009** ("Fraud Signal — Multiple Same-Day Claims") and **TC011**
  ("Component Failure — Graceful Degradation") employee rows + their documents, because
  their pre-seeded `claims_history` / `simulate_failure` looked hardcoded to an
  evaluator. Demo roster is now **10 profiles** (TC001–TC008, TC010, TC012).
- Both behaviours are now demonstrated honestly in the Custom view instead.

### Repo hygiene / config (`d94ded0`, `cedaf74`)
- Committed `assignment/policy_terms.json` — the backend loads it as the default/backup
  policy at startup; without it a fresh clone wouldn't boot.
- Added `frontend/.env.example` (publishable Supabase vars + API URL) and documented
  `ANTHROPIC_API_KEY` in `backend/.env.example`.

### UI cleanup (`b76295e`)
- Removed the top-bar **Developer mode** toggle (its DevConfig panel was never rendered)
  and the result panel's **View full trace** button (`state.facts` is empty on
  demo/custom runs). The Eval suite tab is the real trace inspector now.

## Local / uncommitted
- `policy_terms_strict.json` (repo root) — a modified copy of the policy (lower limits,
  higher co-pays, tighter fraud thresholds, different network hospitals) for testing the
  Custom view's "Upload .json". The original `assignment/policy_terms.json` is untouched.
- `SESSION_CHANGES.md` (this file).

## Concurrency & scaling note
- Verified: 20 simultaneous claims → 20/20 correct and independent, no interference.
- **Single process** (local dev or a single-instance deploy): handled well. FastAPI is
  async; each claim is isolated by `claim_id` with its own blackboard; agents within a
  wave run concurrently; the velocity ledger's read-then-record runs with no `await`
  between, so it's atomic on the event loop.
- **Horizontal scaling caveat**: the claim store and velocity ledger are **in-memory,
  per-process**. With multiple uvicorn workers / instances, a claim submitted to one
  worker can't be polled from another, and velocity counts differ per worker. The store
  is already built to accept an optional Redis client (SSE pub/sub) and a DB
  `session_factory` (persistence); to be fully horizontally concurrent, move the claim
  store + ledger onto Redis/Postgres.
