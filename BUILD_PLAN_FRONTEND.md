# Frontend Build Plan — Claims Processing System

> **Scope:** the Next.js client only. Backend has its own plan (`BUILD_PLAN_BACKEND.md`).
> **Architecture reference:** `ARCHITECTURE.md` (§5 stack, §6.7 SSE schema, §6.8 endpoints, §7.4 "the board IS the UI").
> **Logic contract / copy source:** `PRD.md` (§3 flow, §4.3 collect-all gate, §4.10 financial breakdown, §5 statuses).
> **Visuals:** `DIAGRAMS.md` (diagram 3 = the SSE sequence the UI renders, diagram 7 = the board).
> **Last updated:** 2026-06-21
>
> **The whole product is one screen done extremely well:** submit a claim → watch autonomous agents light up
> on a live board as facts stream in → see early verdicts pop before the claim resolves → land on an explainable
> decision with a full financial breakdown and trace. That real-time board is the **wow factor** and our edge #4
> (ARCHITECTURE §3.2). No login, no roles, no page sprawl (ARCHITECTURE §7.4 / §9 — a deliberate simplification
> from the reference's 9-page, auth-gated app).

---

## 0. Milestones (what "done" means, in order)

| Milestone | Definition of done | Phases | Target |
|-----------|--------------------|--------|--------|
| **A — Board runs on a fixture** | The live board + decision panel render a **recorded SSE fact stream** (a JSON fixture replayed locally). Fully decoupled from the backend — built and demoable before the backend is live. | 0 · 1 · 2 · 3 · 4 | **End of Day 1–2** |
| **B — Wired to live backend** | Submission `POST`s to the deployed Render backend; `EventSource` tails the real `/claims/{id}/stream`; decision + trace come from `GET /claims/{id}`. | 1.4 · 5 | **End of Day 2** |
| **C — Polished + deployed** | Responsive, accessible, animated, error/empty/loading states handled; deployed to Vercel pointing at the Render URL. | 6 | **Day 3** |

**Key decoupling move (FE-1.5):** record one real SSE run as a JSON fixture early, then build the entire board against a fixture replayer. The frontend never blocks on the backend being live — it blocks only on the **fact schema** (ARCHITECTURE §6.7), which is already frozen.

---

## Phase 0 — Scaffold  *(Milestone A)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **FE-0.1** | Next.js 15 (App Router) + TypeScript + Tailwind. Structure: `app/` (routes), `components/`, `lib/` (api, sse, types), `fixtures/` (recorded streams). | — | `next dev` serves a blank styled page. |
| **FE-0.2** | Env: `NEXT_PUBLIC_API_URL` → the Render backend URL. **All `fetch` + `EventSource` call this directly** — never a Next.js `/api/*` route (ARCHITECTURE §5: Vercel Hobby kills SSE proxies at 10 s). `.env.local.example` committed. | FE-0.1 | a constant `API_URL` is read from env; no proxy routes exist. |
| **FE-0.3** | Design tokens in Tailwind config: palette (plum/coral/cream per the reference's polish bar, or our own), status colors (APPROVED green · PARTIAL amber · REJECTED red · MANUAL_REVIEW violet · BLOCKED slate), agent-state colors, fonts. Dark mode optional. | FE-0.1 | tokens usable as Tailwind classes. |
| **FE-0.4** | Base layout + header (product name only — no nav, no auth, no role chips). Skip-to-content link for a11y. | FE-0.1 | one clean shell; no dead nav. |

**Phase 0 exit:** styled Next.js shell, env pointed at the backend URL, no proxy routes, tokens ready.

---

## Phase 1 — Types · API client · SSE hook  *(Milestones A + B)*

> This phase is the contract layer. Build it against the frozen `ARCHITECTURE.md` §6.7 schema so the UI
> is correct before the backend is reachable.

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **FE-1.1** | **TypeScript types** mirroring ARCHITECTURE §6.7 exactly: `Fact` (claim_id, seq, key, author, value, confidence, degraded, derived_from, policy_version_id, reason), `DecisionStatus` union (`BLOCKED/REJECTED/MANUAL_REVIEW/PARTIAL/APPROVED`), `FinancialBreakdown` (the §6.3 object — lines, gross, network_discount, copay, sublimit_cap, approved_amount), `GateIssue`. | — | types compile; a fixture fact narrows cleanly. |
| **FE-1.2** | `api.ts` — `submitClaim(formData) -> {claim_id}` (`POST /claims`, multipart), `getClaim(id) -> ClaimState` (`GET /claims/{id}`). Typed, with error envelopes. | FE-1.1 | functions typed against the §6.8 endpoints. |
| **FE-1.3** | **`useClaimStream(claimId)` hook** — opens `EventSource` on `GET /claims/{id}/stream`, accumulates facts into an ordered map keyed by `seq`, exposes `{facts, agents, decision, status, connected}`. Closes on the `decision` fact. Auto-reconnect with backoff; surfaces `degraded` facts. | FE-1.1 | hook drives a component re-render per incoming fact. |
| **FE-1.4** | **Agent-state derivation** — pure reducer mapping the fact stream → per-agent UI state (`idle → watching → running → posted/skipped/degraded`), using `derived_from` + `reason` (ARCHITECTURE §7.4). A `skipped.*` fact with `PROVABLY_PASS`/`GUARD_FIRED` shows as a dimmed "skipped (provably pass)" chip, not a failure. | FE-1.3 | given the fixture, each agent ends in the correct state. |
| **FE-1.5** | **Fixture replayer** — `replayStream(fixture, onFact)` emits recorded facts on a timer to mimic live SSE. Record one real run once the backend exists; until then, hand-author a fixture covering one approval (TC010), one block (TC001), one reject (TC008). | FE-1.1 | the board (Phase 3) runs entirely offline against a fixture. |

**Phase 1 exit:** a frozen, typed contract + a stream hook + a replayer — the board can be built with zero backend.

---

## Phase 2 — Submission flow  *(Milestone A)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **FE-2.1** | **Claim form** — fields from PRD §2: `member_id`, `policy_id`, `claim_category` (6-way select), `treatment_date`, `claimed_amount`, optional `hospital_name`, `ytd_claims_amount`. Client validation mirrors intake (min amount, required fields) but the **server is authoritative**. | FE-0.3, FE-1.2 | form validates and assembles a submission payload. |
| **FE-2.2** | **Document upload** — multi-file drag-and-drop (images + PDF), per-file thumbnail/name/size, remove, "≥1 document required" (PRD §8.6 #7). | FE-2.1 | files attach to the multipart payload. |
| **FE-2.3** | **Submit → transition** — on submit, call `submitClaim`, get `claim_id`, immediately route/transition to the live board for that claim (no spinner-wait; ARCHITECTURE principle 1). | FE-1.2, FE-2.2 | submit lands on the board in < 1s. |
| **FE-2.4** | **Demo presets** — a "load example claim" menu seeding the form from the 12 cases (great for the interview demo). Maps to the eval fixtures. | FE-2.1 | one click fills TC010 (approval) / TC001 (block) / TC008 (reject). |

**Phase 2 exit:** a member can fill, attach, and submit; the app transitions straight to the live board.

---

## Phase 3 — The live board (the wow factor)  *(Milestone A)*

> This is edge #4 (ARCHITECTURE §3.2 / §7.4) and the visual realization of DIAGRAMS.md diagram 7.
> Agents are nodes; facts light them up as SSE arrives; early verdicts pop before the claim resolves.

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **FE-3.1** | **Board layout** — agents grouped by lane matching the fact graph: *Intake/instant* (per-claim limit, high-value, velocity — these pop at t≈0), *Documents* (detector, extractors, gate), *Synthesis* (semantic map, patient, reconciler, clinical chain), *Rules* (waiting, exclusion, pre-auth, limits, doc-fraud), *Decision* (calculator, aggregator, verifier). | FE-1.4 | static board renders all agent nodes in lanes. |
| **FE-3.2** | **Agent node** component — name, state chip (`idle/watching/running/posted/skipped/degraded`), the fact it produced (verdict/value), confidence, a "why" affordance (`derived_from` lineage). Color by state (FE-0.3). | FE-3.1 | a node reflects its live state + posted fact. |
| **FE-3.3** | **Live wiring** — feed `useClaimStream` (or the replayer) into the board; nodes animate `running → posted` as facts land. **Instant verdicts (per-claim limit, velocity) visibly resolve first** while extractors are still "running" — the concurrency story made visible. | FE-1.3, FE-3.2 | on the fixture, intake nodes settle before document nodes. |
| **FE-3.4** | **Fact ticker / stream rail** — a live, scrolling list of facts as they post (seq, author, key, confidence), the human-readable form of the SSE stream (DIAGRAMS diagram 3). | FE-3.3 | facts scroll in real time; click a fact → highlights its agent node. |
| **FE-3.5** | **Connection + progress affordances** — "agents working" indicator, count of facts posted, graceful "stream closed" on the decision fact. Reconnect banner on drop. | FE-1.3 | stream open/close states are visible and calm. |
| **FE-3.6** | **Motion polish** — subtle enter/settle animations (framer-motion or CSS), respecting `prefers-reduced-motion`. Real-time *feel*, not a progress bar. | FE-3.3 | the board feels alive without being noisy. |

**Phase 3 exit:** a genuinely real-time agent board where parallelism and early verdicts are *visible* — the demo centerpiece.

---

## Phase 4 — Decision, financial breakdown & gate panel  *(Milestone A)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **FE-4.1** | **Decision panel** — large status badge (PRD §5 colors), the member message, ranked reason codes, confidence score with a plain-language band. Appears when the `decision` fact lands. | FE-1.3, FE-0.3 | each of the 5 statuses renders correctly from a fixture. |
| **FE-4.2** | **Financial breakdown** — renders the §6.3 object: per-line covered/excluded (with policy_ref), then **gross → network discount → co-pay → sub-limit cap → approved** as an ordered, readable waterfall. Shows `applied: false` steps explicitly ("no co-pay — dental is 0%") rather than hiding them (ARCHITECTURE §6.3). | FE-1.1, FE-4.1 | TC010 shows 4500 → −20% → −10% → ₹3,240; TC006 shows whitening excluded, ₹8,000 approved. |
| **FE-4.3** | **Collect-all gate panel** (edge #1, PRD §4.3) — when `gate.blocked`, render **all** member-solvable problems in one card: a checklist of every issue with the exact fix, naming docs/names/fields. Emphasize "fix these N things and resubmit" — *not* one-at-a-time. | FE-1.3 | TC001/002/003 fixtures each show their full issue list at once. |
| **FE-4.4** | **Resubmit affordance** — from a blocked claim, "fix & resubmit" returns to the form pre-filled, so the collect-all advantage is felt end-to-end. | FE-4.3, FE-2.1 | one click re-opens the form with prior inputs. |
| **FE-4.5** | **Degraded-but-decided treatment** (TC011) — when the decision carries a manual-review *note* + lowered confidence but stays APPROVED, show the note distinctly from the `MANUAL_REVIEW` *status* (PRD §8.2 C2). | FE-4.1 | TC011 fixture shows APPROVED ₹4,000 + a visible degradation note. |

**Phase 4 exit:** the outcome is explainable at a glance — status, money math, and (when blocked) every fix in one place.

---

## Phase 5 — Live backend wiring & trace  *(Milestone B)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **FE-5.1** | Point `api.ts` + `useClaimStream` at the **deployed Render URL**; submit a real claim end-to-end; confirm CORS works (backend BE-5.6). | Backend Milestone B | a real submission streams real facts and lands a real decision. |
| **FE-5.2** | **Trace view** — the full fact list from `GET /claims/{id}` sorted by `seq`: each fact with author, value, confidence, `derived_from` lineage, policy refs, degraded flag. This is the Observability (20%) surface. | FE-1.2 | a reviewer can reconstruct *why* from the trace alone. |
| **FE-5.3** | **Lineage highlight** — clicking a fact highlights its `derived_from` ancestors on the board (the audit story, visual). | FE-5.2, FE-3.2 | clicking `decision` traces back through its inputs. |
| **FE-5.4** | **Reconnect / replay-on-load** — opening a claim mid-flight replays facts-so-far then live-tails (backend BE-5.5 already replays); refreshing never loses state. | FE-1.3 | refresh during a run resumes cleanly. |
| **FE-5.5** | *(optional, needs a backend list endpoint)* **Recent claims** list. Flag: the day-1 API (§6.8) has no list endpoint — either add `GET /claims` backend-side or skip. Default: **skip** for the demo. | — | decision recorded; not built unless the endpoint is added. |

**Phase 5 exit:** the UI runs on the live deployed backend with a demo-grade, lineage-linked trace.

---

## Phase 6 — Polish, accessibility & deploy  *(Milestone C)*

| ID | Task | Depends on | Done when |
|----|------|------------|-----------|
| **FE-6.1** | **States** — loading, empty, and error states for submit, stream, and fetch; never a blank screen; a dropped stream shows a calm reconnect, not a crash. | FE-5.1 | each failure path has a designed state. |
| **FE-6.2** | **Responsive** — the board reflows on tablet/narrow; lanes stack; the demo works on a projector and a laptop. | FE-3.1 | usable from ~768px up. |
| **FE-6.3** | **Accessibility** — semantic landmarks, focus management on transition, ARIA live region for newly-posted facts (announce decisions), color-contrast on all status colors, `prefers-reduced-motion`. | FE-3.6, FE-4.1 | keyboard-navigable; screen reader announces the decision. |
| **FE-6.4** | **Deploy to Vercel** (hobby) — auto-deploy from GitHub, `NEXT_PUBLIC_API_URL` set to the Render URL, confirm SSE works browser→Render directly (no proxy). Warm the Render dyno before demoing (it sleeps at 15 min idle). | FE-0.2, FE-5.1 | public Vercel URL drives a live claim against Render. |
| **FE-6.5** | **Demo script + README** — the 60-second story: submit TC010 → watch instant verdicts pop while extraction runs → approved with the discount→copay waterfall; then TC001 → collect-all gate shows all fixes at once. | all | a fresh viewer can run the demo from the README. |

**Phase 6 exit (Milestone C):** polished, accessible, responsive, deployed — demo-ready on a public URL.

---

## Build-order summary (the dependency spine)

```
0.1 scaffold ─► 0.2 env (direct-to-Render) ─► 0.3 tokens ─► 0.4 shell
  └─► 1.1 types(§6.7) ─► 1.2 api(§6.8) ─► 1.3 useClaimStream ─► 1.4 agent-state reducer ─► 1.5 fixture replayer
        ├─► 2.1 form ─► 2.2 upload ─► 2.3 submit→board ─► 2.4 demo presets
        └─► 3.1 board ─► 3.2 agent node ─► 3.3 live wiring ─► 3.4 ticker ─► 3.5 conn ─► 3.6 motion   ← WOW
              └─► 4.1 decision ─► 4.2 financial waterfall ─► 4.3 collect-all gate ─► 4.4 resubmit ─► 4.5 degraded note
                    └─ (Milestone A: all of the above on a FIXTURE) ─┐
                                                                     └─► 5.1 wire live ─► 5.2 trace ─► 5.3 lineage ─► 5.4 reconnect (Milestone B)
                                                                           └─► 6.* states · responsive · a11y · Vercel (Milestone C)
```

## Backend dependencies (explicit handoffs)

| Frontend needs | From backend task | Contract |
|----------------|-------------------|----------|
| Fact shape for types | (frozen design) | ARCHITECTURE §6.7 |
| `POST /claims` | BE-5.3 | returns `{claim_id}` immediately |
| `GET /claims/{id}` | BE-5.4 | full state + facts by `seq` |
| `GET /claims/{id}/stream` | BE-5.5 | SSE, replay-then-tail, closes on `decision` |
| CORS for browser→Render | BE-5.6 | Vercel origin allowed |
| `financial_breakdown` object | BE-4.18 | §6.3 schema (waterfall fields) |
| `gate.blocked` issue list | BE-4.8 | collect-all array |

> Because of the fixture replayer (FE-1.5), **none of Phases 2–4 block on the backend** — only Phase 5 does.
> Frontend Milestone A can be finished and demoed while the backend is still on its own Milestone A.

## Deliberately NOT built (vs the reference)

- **No auth, no login, no role switching** (ARCHITECTURE §7.4 / §9) — the reference has member/ops roles + guards; we ship one open view. Less code, faster demo, same core story.
- **No policy editor / PolicyStudio** — we version-stamp policy in the trace (ARCHITECTURE §6.5), not a live editor UI.
- **No RAG policy-assistant side-panel** (ARCHITECTURE §3.3) — deliberately conceded; AI-Integration weight is carried on the core flow (clinical coherence + extraction), not a Q&A box.
- **No separate ops dashboard / worklist / fraud console** — a single trace view serves the reviewer; the board *is* the console.

These cuts are the point: a smaller, sharper surface that makes the real-time board and the explainable decision the entire experience.
