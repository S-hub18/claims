# PRD — Claims Processing: User Flow & Decision Logic

> **Purpose:** The canonical, architecture-agnostic specification of *what the system does and why*.
> Any architecture (sequential pipeline, blackboard, etc.) must implement exactly this logic.
> **Source of truth ("the bible"):** `assignment/assignment.md`, `assignment/policy_terms.json`,
> `assignment/test_cases.json`, `assignment/sample_documents_guide.md`.
> Every rule below is validated against those files; the validating test case is cited inline.
> **Last updated:** 2026-06-21

---

## 0. How to read this

- §1–§3 = the actors, inputs, and the end-to-end flow (the part you asked for — the user journey).
- §4 = each stage's logic in detail, with exact policy values and the test case that proves it.
- §5 = decision status definitions + precedence (the rules that resolve conflicts).
- §6 = policy reference tables (all numbers copied from `policy_terms.json`).
- §7 = all 12 test cases mapped to the flow (the validation matrix).
- §8 = interpretation calls + improvements over a naive literal reading of the policy.

Two notational conventions:
- **STOP** = the claim halts and returns a member-facing message; no decision is produced.
- **Verdict** = a single rule's outcome: `PASS` / `FAIL` / `FLAG` / `SKIPPED`.

---

## 1. Actors & Entry Points

| Actor | Does | Sees |
|-------|------|------|
| **Member** (employee) | Submits a claim: details + documents | Live progress, the decision, the reason, what to do next |
| **Ops reviewer** | Reviews `MANUAL_REVIEW` claims; can override | Full trace of every check for any claim |

A claim is always filed against **one** `claim_category`:
`CONSULTATION · DIAGNOSTIC · PHARMACY · DENTAL · VISION · ALTERNATIVE_MEDICINE`.

---

## 2. Claim Submission (Inputs)

```
member_id          required   must exist in policy roster
policy_id          required   "PLUM_GHI_2024"
claim_category     required   one of the 6 categories
treatment_date     required   ISO date
claimed_amount     required   INR, number
hospital_name      optional   used for network-discount lookup
ytd_claims_amount  optional   member's year-to-date approved total (annual-limit check)
claims_history     optional   [{claim_id, date, amount, provider}] (fraud velocity check)
documents          required   one or more images/PDFs
```

> The 12 eval cases ship as structured JSON, not images. See §8.4 for how they are ingested.

---

## 3. End-to-End User Flow

```
                          ┌─────────────────────────────┐
                          │   MEMBER SUBMITS A CLAIM     │
                          └──────────────┬──────────────┘
                                         ▼
   ┌──────────────────────────────  STAGE 1: INTAKE  ──────────────────────────────┐
   │  • member_id exists?            ── no ─►  STOP: "Member not found on policy"    │
   │  • claimed_amount ≥ ₹500?       ── no ─►  STOP: "Below minimum claimable ₹500"  │
   │  • (submission deadline check — DISABLED for eval; see §8.3)                    │
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                           ▼
   ┌──────────────────────  STAGE 2: DOCUMENT EXTRACTION  ─────────────────────────┐
   │  For each uploaded file:                                                       │
   │   • split if one file embeds multiple doc types (§8.5)                         │
   │   • classify type · assess readability · extract fields                        │
   │     (patient, doctor, registration, diagnosis, treatment, line items,          │
   │      amounts, dates) — each with confidence + source snippet                   │
   │   • low-confidence load-bearing field on a readable doc → re-read once (§4.2)  │
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                           ▼
   ┌──────────────  STAGE 3: DOCUMENT VERIFICATION GATE (after extraction)  ────────┐
   │  3a required types present for category?  ── no ─► STOP: WRONG/MISSING (TC001)  │
   │  3b every required doc readable?          ── no ─► STOP: re-upload that doc      │
   │                                                     (TC002 — do NOT reject)     │
   │  3c all docs same patient = member/dependent? no ─► STOP: name both (TC003)     │
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                           ▼  (documents are valid; begin adjudication)
   ┌──────────────────────  STAGE 4: SEMANTIC MAPPING  ────────────────────────────┐
   │  Map free text → policy vocabulary:                                            │
   │   • diagnosis → waiting condition  ("Type 2 Diabetes Mellitus" → diabetes)     │
   │   • treatment/line items → exclusion candidates ("Teeth Whitening" → cosmetic) │
   │   • detect high-value tests (MRI / CT / PET)                                    │
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                           ▼
   ┌──────────────────────  STAGE 5: POLICY RULE CHECKS  ──────────────────────────┐
   │   Waiting period · Coverage & exclusions · Pre-authorization · Limits · Fraud   │
   │   (each emits a verdict; see §4.5–§4.9)                                         │
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                           ▼
   ┌──────────────────  STAGE 6: FINANCIAL CALCULATION  ───────────────────────────┐
   │   covered lines → gross → NETWORK DISCOUNT first → CO-PAY → SUB-LIMIT cap        │
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                           ▼
   ┌──────────────────────  STAGE 7: DECISION  ────────────────────────────────────┐
   │   Aggregate verdicts + amount → APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW   │
   │   + approved amount + ranked reasons + confidence score                        │
   └──────────────────────────────────────┬─────────────────────────────────────────┘
                                           ▼
   ┌──────────────────────  STAGE 8: VERIFY & EXPLAIN  ────────────────────────────┐
   │   Independent check of decision vs evidence → may escalate to MANUAL_REVIEW    │
   │   Finalise confidence; emit full trace                                         │
   └────────────────────────────────────────────────────────────────────────────────┘

   At every stage: a component failure is recorded, the flow continues with partial
   data, confidence drops, and "manual review recommended" is noted (§4.14, TC011).
```

---

## 4. Stage Logic (validated)

### 4.1 Intake validation
- **Member exists:** `member_id` must be in `members[]`. Else **STOP** — "Member not found on policy."
- **Minimum amount:** `claimed_amount ≥ submission_rules.minimum_claim_amount` (₹500). Else **STOP**.
- **Submission deadline:** `submission_rules.deadline_days_from_treatment` = 30. **Disabled for the eval** (all test dates are 2024; measuring against the current date would reject all 12 — see §8.3).

### 4.2 Document extraction
- Classify `doc_type`; assess `readable` + quality issues; extract fields with **per-field confidence + source_text**.
- Handle messy inputs (per `sample_documents_guide.md`): handwriting, rubber stamps, phone photos, multilingual, multi-page. A stamp/blur over a field → lower that field's confidence, don't fail the whole doc.
- Validate doctor registration format (state-coded, e.g. `KA/45678/2015`, `AYUR/KL/2345/2019`); malformed → low confidence + flag.
- **Self-correction:** if a *load-bearing* field (per §4.13) is null/low-confidence on a *readable* doc, re-read once with a stronger model; keep the higher-confidence value. Never blocks the critical path.
- **Output:** one `ExtractionResult` per document.

### 4.3 Document verification gate — **runs after extraction** (critical: see §8.1)
Order of checks (first failure STOPs):
1. **Readability (3b):** any required doc `readable=false` → **STOP**, ask re-upload of *that specific* document, keep the rest. *Never reject for this.* — **TC002**
2. **Required types present (3a):** compare uploaded types vs `document_requirements[category].required`.
   - Missing a required type → **STOP**. Message names *what was uploaded* and *what is still needed*.
   - If an out-of-category type was uploaded → call it out as "not used for a {category} claim."
   - **TC001:** two PRESCRIPTIONs for CONSULTATION (needs PRESCRIPTION + HOSPITAL_BILL) → "you uploaded prescriptions; a hospital bill is required."
3. **Patient consistency (3c):** every doc's patient must resolve to the **member or a covered dependent**. Mismatch → **STOP**, naming the conflicting names. — **TC003** (Rx "Rajesh Kumar" vs bill "Arjun Mehta"; Arjun Mehta is neither the member nor dependent Arjun *Kumar*).
4. **Missing decision-critical field** (readable doc, but e.g. a bill with no total and no line items) → **STOP**, ask the member to supply it. (Narrow; never guesses.)

### 4.4 Semantic mapping
Bridges messy text → policy keys. Produces:
- `waiting_condition` — maps diagnosis to a `waiting_periods.specific_conditions` key (or null).
- `exclusion_candidates` — maps diagnosis/treatment/line items to exclusion vocabulary.
- `high_value_tests` present — MRI / CT Scan / PET Scan detection for pre-auth.
- `category_match` — does the treatment match the filed category? (advisory)

### 4.5 Rule — Waiting Period
`days_enrolled = treatment_date − member.join_date`.
- **Initial wait:** if `days_enrolled < initial_waiting_period_days` (30) → **FAIL** (`WAITING_PERIOD`).
- **Condition-specific:** if `waiting_condition` set and `days_enrolled < specific_conditions[condition]` → **FAIL**. State eligible date = `join_date + waiting_days`.
- **Pre-existing:** if a PED marker is present and `days_enrolled < 365` → **FAIL** (enforced only when member data carries the marker; none do in the eval).
- Otherwise **PASS**.
- **TC005:** EMP005 joined `2024-09-01`, treatment `2024-10-15` → 44 days. diabetes wait = 90. `44 < 90` → **FAIL**; eligible from `2024-09-01 + 90d = 2024-11-30`. (Note: 44 > 30, so the *initial* wait passes; the *diabetes* wait binds.)

### 4.6 Rule — Coverage & Exclusions
Two distinct mechanisms — **do not conflate** (this is what separates TC012 REJECT from TC006 PARTIAL):

**(a) Whole-claim exclusion** — the claim's *primary diagnosis/treatment* maps to `exclusions.conditions` → **FAIL whole claim** (`EXCLUDED_CONDITION`).
- **TC012:** diagnosis "Morbid Obesity", treatment "Bariatric Consultation + Diet Program" → maps to "Obesity and weight loss programs" / "Bariatric surgery" → **REJECTED**.

**(b) Line-item exclusion** — a *specific line* maps to a category exclusion (`opd_categories.<cat>.excluded_procedures/items`, `exclusions.dental_exclusions/vision_exclusions`) while the claim's core purpose is covered → **disallow that line**, keep the rest → leads to **PARTIAL**.
- **TC006:** dental bill = Root Canal ₹8,000 (in `covered_procedures`) + Teeth Whitening ₹4,000 (in dental `excluded_procedures`) → disallow whitening, approve root canal → **PARTIAL ₹8,000**.

**(c) Coverage check** — for DENTAL/VISION, a line must be in `covered_procedures`/`covered_items` to be payable.

### 4.7 Rule — Pre-Authorization
- For **DIAGNOSTIC**: if a high-value test (`high_value_tests_requiring_pre_auth` = MRI, CT Scan, PET Scan) is present **and** `claimed_amount > pre_auth_threshold` (₹10,000) **and** no pre-auth on file → **FAIL** (`PRE_AUTH_MISSING`). Tell the member to obtain pre-auth and resubmit.
- General `pre_authorization.required_for`: PET scan (any amount), major surgery, planned hospitalization → pre-auth required.
- **Assumption:** pre-auth is *absent unless explicitly supplied* (no submission field provides one; no test supplies one).
- **TC007:** DIAGNOSTIC, MRI Lumbar Spine, ₹15,000 > ₹10,000, no pre-auth → **REJECTED**.

### 4.8 Rule — Limits  *(category-aware — see §8.1 A5; a blanket "claimed > ₹5,000 → reject" FAILS TC006)*
The per-claim ceiling is **category-aware**, evaluated on the **covered** amount (after line-item exclusions), not raw `claimed_amount`:

> **binding_ceiling = max(per_claim_limit ₹5,000, category sub_limit)**

- **When ₹5,000 is the binding cap** (category sub_limit ≤ ₹5,000 → **CONSULTATION** ₹2,000, **VISION** ₹5,000): covered > ₹5,000 → **FAIL `PER_CLAIM_EXCEEDED`** (HARD REJECT). State the limit + amount. — **TC008** (consultation covered ₹7,500 > ₹5,000 → REJECTED).
- **When the category sub-limit is the binding cap** (sub_limit > ₹5,000 → **DENTAL/DIAGNOSTIC** ₹10,000, **PHARMACY** ₹15,000, **ALT-MED** ₹8,000): covered > sub_limit → **CAP (reduce)** to sub_limit; *do not reject*. — **TC006** (dental covered ₹8,000 ≤ ₹10,000 → PARTIAL ₹8,000, NOT rejected despite claimed ₹12,000).
- **Why category-aware:** a global ₹5,000 reject would (a) wrongly reject TC006 and (b) make the ₹8,000–₹15,000 sub-limits unreachable. Per-claim-limit binds only where it is the *lowest applicable* cap.
- **Consultation also has a per-LINE sub-limit:** the ₹2,000 caps the consultation-fee *line* (applied in §4.10) — separate from the ₹5,000 whole-claim reject above (see §8.1 A1).
- **Annual OPD limit:** if `ytd_claims_amount + approved > annual_opd_limit` (₹50,000) → cap the excess. (Not binding in eval; max ytd given is ₹10,000.)
- **Sum insured:** `sum_insured_per_employee` (₹500,000) is the overall annual ceiling — checked against cumulative utilisation (far above any single eval value).
- **Family floater:** combined ₹150,000 across member + covered family. Enforced when family utilisation is supplied (not in eval).

### 4.9 Rule — Fraud & Anomaly → produces **FLAG** (never auto-reject)
- **Same-day velocity:** count claims (incl. the current one) on `treatment_date`. If `> same_day_claims_limit` (2) → **FLAG**. — **TC009** (3 history + 1 current = 4 > 2 → MANUAL_REVIEW).
- **Monthly velocity:** if month count `> monthly_claims_limit` (6) → **FLAG**.
- **High value:** if `claimed_amount ≥ auto_manual_review_above` (₹25,000) → **FLAG**.
- **Document anomalies:** extraction `fraud_signals` (altered/overwritten amounts, conflicting ORIGINAL/DUPLICATE stamps, line items not summing to total) contribute to a fraud score; `≥ fraud_score_manual_review_threshold` (0.80) → **FLAG**.
- A FLAG routes an otherwise-approvable claim to **MANUAL_REVIEW** (it does not override a definitive rejection — §5).

### 4.10 Financial calculation — **order is load-bearing** (TC010)
```
1. covered_lines  = line items minus (whole-claim excluded? none here) minus disallowed lines (§4.6b)
2. gross          = Σ covered_lines        (fallback: bill total, else claimed_amount)
3. discount_pct   = network_discount_percent if hospital ∈ network_hospitals else 0
                    (consultation 20%, diagnostic 10%, all others 0%)
   post_discount  = gross − gross × discount_pct          ── NETWORK DISCOUNT FIRST
4. copay_pct      = copay_percent (consultation 10%, others 0%; pharmacy branded lines 30%)
   approved       = post_discount − post_discount × copay_pct   ── CO-PAY ON POST-DISCOUNT
5. sub-limit cap  = consultation: cap the consultation-fee line at ₹2,000 (per-line)
                    others: cap `approved` at category sub_limit
6. approved_amount = result    (all arithmetic in exact decimal; no float drift)
```
Validation:
- **TC004** (City Clinic, not network): gross 1500 → no discount → 10% co-pay = 150 → **₹1,350** ✓
- **TC010** (Apollo, network): 4500 → −20% = 3600 → −10% = **₹3,240** ✓ (note: 3240 > consultation ₹2,000 ⇒ proves the ₹2,000 is *not* a whole-claim cap)
- **TC006** (dental): covered = 8000 (whitening disallowed) → 0% co-pay → **₹8,000** ✓
- **TC011** (alt-med): 4000 → 0% co-pay → **₹4,000** ✓

### 4.11 Decision aggregation
See §5 for status definitions + precedence. Produces: `status`, `approved_amount`, ranked `reason_codes`, `member_message`, `confidence`.

### 4.12 Verification
An independent check of the decision against the *extracted source evidence* (not just the verdicts). If it finds the evidence does not support an `APPROVED`/`PARTIAL` outcome → escalate to **MANUAL_REVIEW** with a reason. Does not block the decision from being shown first.

### 4.13 Confidence scoring (explainable, component-based)
```
confidence = f(extraction_quality, rule_certainty, completeness, verifier_agreement)
             − degradation_penalty × (component failures)
```
- **extraction_quality** — avg confidence of *load-bearing* fields, claim-type-aware:
  - all types: patient identity + total amount
  - PHARMACY: + medicine list match; DENTAL: + procedure identity; DIAGNOSTIC: + tests performed
- **rule_certainty** — avg certainty of evaluated rules.
- **completeness** — fraction of expected checks that actually ran (drops on component failure).
- **verifier_agreement** — verifier confidence when it agrees.
- **Must satisfy:** TC004 **> 0.85**, TC012 **> 0.90**, TC011 **measurably lower** than a clean approval.

### 4.14 Graceful degradation
Any component failure (LLM timeout, parse error, bad input) is **recorded**, the flow **continues** with whatever is available, **confidence drops**, and **"manual review recommended"** is appended. The system never crashes / never 500s.
- **TC011:** a simulated non-critical component (fraud check) fails → still **APPROVED ₹4,000**, failure visible in trace, confidence below a clean approval, manual-review note attached. (Status stays APPROVED — see §8.2: a recommendation note ≠ the `MANUAL_REVIEW` status.)

---

## 5. Decision Status — Definitions & Precedence

| Status | Meaning |
|--------|---------|
| **BLOCKED** (no decision) | A document problem stopped the claim before adjudication (TC001–003). Output = problem + fix. |
| **REJECTED** | A definitive policy violation: whole-claim exclusion, waiting period, missing pre-auth, or per-claim-limit exceeded. |
| **MANUAL_REVIEW** | Routed to a human: fraud flag, claimed ≥ ₹25,000, confidence below threshold, or unresolved uncertainty. |
| **PARTIAL** | Some line items excluded, ≥1 covered line approved. |
| **APPROVED** | All checks pass; full covered amount payable. |

**Precedence (first match wins):**
```
1. Document problem present              → BLOCKED          (TC001/02/03)
2. Any definitive violation              → REJECTED         (TC005/07/08/12)
   reason rank: EXCLUDED_CONDITION > WAITING_PERIOD > PRE_AUTH_MISSING > PER_CLAIM_EXCEEDED
   (list all that apply; primary = highest rank — TC012 shows EXCLUDED over PER_CLAIM)
3. Fraud FLAG / high-value / low-conf     → MANUAL_REVIEW    (TC009)
4. ALL covered lines excluded (covered=0) → REJECTED         (fully non-covered; not PARTIAL ₹0)
5. Some lines excluded, ≥1 approved       → PARTIAL          (TC006)
6. Otherwise                              → APPROVED         (TC004/10/11)
Overlay: component failure → keep status, add "manual review recommended" + lower confidence (TC011)
```
> A fraud FLAG escalates an *otherwise-approvable* claim to MANUAL_REVIEW; it does **not** override a definitive REJECTED (a clear rule violation needs no human). Fraud signals are always recorded in the trace regardless. (Refinement of the earlier open question — see §8.2 B3.)

---

## 6. Policy Reference (from `policy_terms.json`)

**Coverage:** sum insured 500,000 · annual OPD 50,000 · **per-claim 5,000** · family floater 150,000

**Categories**

| Category | sub_limit | co-pay | network disc. | pre-auth | doc note |
|----------|-----------|--------|---------------|----------|----------|
| CONSULTATION | 2,000 | 10% | 20% | no | Rx + Bill |
| DIAGNOSTIC | 10,000 | 0% | 10% | MRI/CT/PET > 10,000 | Rx + Lab + Bill |
| PHARMACY | 15,000 | 0% (branded 30%) | — | no | Rx + Pharmacy Bill |
| DENTAL | 10,000 | 0% | — | no | Bill (report optional — §8.1 B1) |
| VISION | 5,000 | 0% | — | no | Rx + Bill |
| ALTERNATIVE_MEDICINE | 8,000 | 0% | — | no | Rx + Bill; reg. practitioner; ≤20 sessions/yr |

**Waiting periods (days):** initial 30 · pre-existing 365 · diabetes 90 · hypertension 90 · thyroid 90 · joint_replacement 730 · maternity 270 · mental_health 180 · obesity_treatment 365 · hernia 365 · cataract 365

**Document requirements (required)**
- CONSULTATION: PRESCRIPTION, HOSPITAL_BILL · DIAGNOSTIC: PRESCRIPTION, LAB_REPORT, HOSPITAL_BILL · PHARMACY: PRESCRIPTION, PHARMACY_BILL · DENTAL: HOSPITAL_BILL · VISION: PRESCRIPTION, HOSPITAL_BILL · ALTERNATIVE_MEDICINE: PRESCRIPTION, HOSPITAL_BILL

**Fraud thresholds:** same-day 2 · monthly 6 · high-value 25,000 · auto-manual-review ≥ 25,000 · fraud-score ≥ 0.80

**Network hospitals:** Apollo, Fortis, Max, Manipal, Narayana, Medanta, Kokilaben, Aster CMI, Columbia Asia, Sakra World

---

## 7. Validation Matrix — 12 Test Cases Through the Flow

| TC | Category | Stops at | Expected | Logic that produces it |
|----|----------|----------|----------|------------------------|
| 001 | CONSULTATION | Gate 3a | BLOCKED | Two prescriptions, no bill → MISSING required HOSPITAL_BILL |
| 002 | PHARMACY | Gate 3b | BLOCKED | Pharmacy bill unreadable → re-upload that doc, don't reject |
| 003 | CONSULTATION | Gate 3c | BLOCKED | Rx "Rajesh Kumar" ≠ bill "Arjun Mehta" → patient mismatch |
| 004 | CONSULTATION | Decision | APPROVED ₹1,350 | 1500 − 10% co-pay |
| 005 | CONSULTATION | Waiting | REJECTED | 44 days < 90-day diabetes wait; eligible 2024-11-30 |
| 006 | DENTAL | Decision | PARTIAL ₹8,000 | Root canal covered; whitening line excluded |
| 007 | DIAGNOSTIC | Pre-auth | REJECTED | MRI ₹15,000 > ₹10,000, no pre-auth |
| 008 | CONSULTATION | Limits | REJECTED | ₹7,500 > ₹5,000 per-claim (hard reject) |
| 009 | CONSULTATION | Fraud | MANUAL_REVIEW | 4th same-day claim > limit 2 |
| 010 | CONSULTATION | Decision | APPROVED ₹3,240 | Apollo: −20% then −10% (order matters) |
| 011 | ALTERNATIVE_MEDICINE | Decision | APPROVED ₹4,000 (degraded) | Component fails; continue, lower confidence, note review |
| 012 | CONSULTATION | Exclusion | REJECTED | Obesity/bariatric whole-claim exclusion (> per-claim too; exclusion ranks first) |

---

## 8. Interpretation Calls & Improvements (gaps in the literal policy)

### 8.1 Calls forced or clarified by the data
- **A1 — Consultation sub-limit is NOT a whole-claim cap.** TC010 approves ₹3,240 > ₹2,000. The ₹2,000 caps only the consultation-fee line; `per_claim_limit` (₹5,000) is the whole-claim ceiling. A naive whole-claim cap fails TC010.
- **A2 — per-claim-limit REJECTS, sub-limit REDUCES.** TC008 rejects at ₹7,500; it is not capped to ₹5,000.
- **A3 — Discount strictly before co-pay** (TC010). Only consultation/diagnostic have a network discount.
- **A4 — Gate runs AFTER extraction.** TC002 needs extracted readability; TC003 needs extracted patient names. A pre-extraction gate cannot decide these.
- **A5 — Per-claim limit is category-aware, NOT a global ₹5,000 reject.** binding ceiling = `max(₹5,000, category sub_limit)` on the *covered* amount. A blanket "claimed > ₹5,000 → reject" wrongly rejects TC006 (dental ₹12,000 → expected PARTIAL ₹8,000) and makes the ₹8,000–₹15,000 sub-limits unreachable. ₹5,000 rejects only where it is the lowest applicable cap (consultation, vision); higher sub-limits *cap* instead. See §4.8. (This was a real bug in an earlier draft of this PRD.)
- **B1 — Dental report is OPTIONAL.** `opd_categories.dental.requires_dental_report:true` contradicts `document_requirements.DENTAL` (report optional). TC006 has no dental report and is approved → **`document_requirements` is authoritative.**

### 8.2 Conflict-resolution calls (untested but decided)
- **B2 — Reason ranking: exclusion > waiting > pre-auth > per-claim-limit.** TC012 violates exclusion *and* per-claim-limit but expects `EXCLUDED_CONDITION`. List all applicable, primary = highest rank.
- **B3 — REJECTED outranks MANUAL_REVIEW.** A definitive policy violation rejects; a fraud FLAG only escalates an otherwise-approvable claim. (Fraud signals still recorded in the trace.)
- **C2 — A "manual review recommended" *note* is not the `MANUAL_REVIEW` *status*.** TC011 stays APPROVED with a note; TC009 is the status. Keep them as separate fields.

### 8.3 Traps to avoid
- **C1 — Submission deadline (30 days) must be disabled for the eval.** Test treatment dates are 2024; measuring against the current date rejects all 12. Disable, or measure against a fixed as-of date.

### 8.4 Test-case ingestion (decide before building the eval)
The 12 cases are structured JSON in two shapes:
- TC001–003 give `actual_type`/`quality`/`patient_name_on_doc`, no content → exercise the **gate**.
- TC004–012 give pre-extracted `content`, no images → exercise the **decision logic**.

Faithful options: **(a)** render synthetic documents and run real vision (proves extraction, makes confidence a live metric), or **(b)** inject content after extraction (deterministic, bypasses vision). **Plan:** support both — render a few representative docs to prove vision, content-inject for the deterministic full suite.

### 8.5 Improvements over the literal policy (gap-closing logic)
- **Multi-doc-in-one-file:** a single PDF embedding multiple document types is split into typed segments before extraction (the policy assumes one type per file; reality doesn't).
- **Patient = member OR covered dependent:** validate against the member *and* `dependents`/`covered_relationships`, not just the member (TC003's "Arjun Mehta" is neither the member nor dependent "Arjun Kumar").
- **Amount reconciliation:** if `claimed_amount` differs materially from the extracted bill total, use the extracted total and surface the discrepancy as an anomaly signal.
- **Cross-document coherence (improvement, not in reference):** verify the prescription → lab → bill chain is about one episode (same patient, sane dates, ordered tests ≈ performed tests ≈ billed items). Incoherence → anomaly signal / lower confidence.
- **Indian name resolution:** treat initials, dropped middle names, and maiden/married surnames structurally, not by raw character distance, to avoid both false mismatches and false matches.
- **Doctor registration validation:** state-coded format check; malformed → lower confidence, flag (does not fail the doc).
- **Pharmacy generic mandatory / branded co-pay:** branded lines carry 30% co-pay; if `generic_mandatory` and a generic substitute exists, flag the branded portion. (Enforced when the formulary signal is present.)

---

### 8.6 Real policy scenarios NOT exercised by the 12 test cases (covered for completeness)

These are rules/data present in `policy_terms.json` that no test case triggers, but a complete system must handle:

| # | Scenario | Logic |
|---|----------|-------|
| 1 | **Policy in-force window** | `treatment_date` must fall within `policy_start_date` (2024-04-01) … `policy_end_date` (2025-03-31) and `renewal_status` = ACTIVE. Outside → REJECT (`POLICY_NOT_IN_FORCE`). |
| 2 | **Treatment before enrollment** | if `treatment_date < member.join_date` → invalid (`days_enrolled` negative) → REJECT / MANUAL_REVIEW. |
| 3 | **All covered lines excluded** | covered = ₹0 after exclusions → REJECTED (not PARTIAL ₹0). See §5 rule 4. |
| 4 | **Alt-medicine covered system** | treatment must be one of `covered_systems` (Ayurveda, Homeopathy, Unani, Siddha, Naturopathy). Non-covered system → REJECT. (TC011 Panchakarma = Ayurveda ✓.) |
| 5 | **Category mismatch** | if the treatment clearly doesn't match the filed `claim_category` (semantic mapper confident) → MANUAL_REVIEW (don't silently mis-adjudicate). |
| 6 | **Pre-auth supplied but expired** | if a pre-auth reference is provided but older than `pre_authorization.validity_days` (30) → treat as missing. |
| 7 | **No documents uploaded** | zero documents → STOP ("at least one document required"). |
| 8 | **MANUAL_REVIEW approved amount** | carry the *provisional* computed amount (held, not paid) so the reviewer sees the recommendation; not ₹0. |

> Items 1–2 are pre-adjudication validations (extend Stage 1). Items 3–5 extend the rule/decision logic. Items 6–8 are clarifications. None affect the 12-case eval; all are required for a production-complete system.

---

*This PRD is the logic contract. Architecture documents (`ARCHITECTURE.md`) describe *how* to execute it; this describes *what* must be true. Validated against the assignment source files on 2026-06-21.*
