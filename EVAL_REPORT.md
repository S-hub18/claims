# Eval Report — Claims Adjudication

*All 12 test cases from `assignment/test_cases.json` run through the live engine. For each
case: the decision the system produced, the full ordered fact trace, and whether it matched
the expected outcome.*

---

## How to reproduce

```bash
cd backend
uv run python -m tests.eval.run_eval     # scorecard
uv run pytest tests/eval/                 # enforces the 12/12 floor
```

The suite runs against the deterministic `FakeLLMClient` — the test cases carry each
document's content inline, so the eval is **reproducible and uses zero API calls**. The
grader (`tests/eval/run_eval.py`) checks structured fields (status, amount, ranked reasons,
confidence threshold) **and** message-quality substrings (e.g. TC001 must name both
`HOSPITAL_BILL` and `PRESCRIPTION`; TC011 must say "manual review" and "component"). A case
is green only when *every* check passes.

## Summary

| TC | Scenario | Expected | Produced | Amount | Confidence | Result |
|---|---|---|---|---|---|---|
| 001 | Wrong document uploaded | BLOCKED | **BLOCKED** | — | 0.95 | ✅ |
| 002 | Unreadable document | BLOCKED | **BLOCKED** | — | 0.95 | ✅ |
| 003 | Different patients | BLOCKED | **BLOCKED** | — | 0.95 | ✅ |
| 004 | Clean consultation | APPROVED ₹1350 | **APPROVED** | ₹1350 | 0.95 | ✅ |
| 005 | Diabetes in waiting period | REJECTED (WAITING_PERIOD) | **REJECTED** | — | 0.95 | ✅ |
| 006 | Dental + cosmetic line | PARTIAL ₹8000 | **PARTIAL** | ₹8000 | 0.95 | ✅ |
| 007 | MRI without pre-auth | REJECTED (PRE_AUTH_MISSING) | **REJECTED** | — | 0.95 | ✅ |
| 008 | Per-claim limit exceeded | REJECTED (PER_CLAIM_EXCEEDED) | **REJECTED** | — | 0.95 | ✅ |
| 009 | Many same-day claims | MANUAL_REVIEW | **MANUAL_REVIEW** | ₹4320 | 0.95 | ✅ |
| 010 | Network hospital discount | APPROVED ₹3240 | **APPROVED** | ₹3240 | 0.95 | ✅ |
| 011 | Component failure mid-run | APPROVED, lowered conf | **APPROVED** | ₹4000 | 0.70 | ✅ |
| 012 | Bariatric (excluded) | REJECTED (EXCLUDED_CONDITION) | **REJECTED** | — | 0.95 | ✅ |

**12 / 12 GREEN.** Every case matched, including the exact payouts the assignment specifies
(TC004 ₹1350, TC006 ₹8000, TC010 ₹3240) and both confidence bars (TC004 > 0.85, TC012 >
0.90, TC011 visibly lowered to 0.70).

A note on reading the traces: fact `#0` is always the `submission` seed. Facts `#1`–`#N`
are posted in the order agents *finished*, which races run-to-run (the agents fire
concurrently) — so the numeric order varies, but the decision does not, because the
aggregator reads the complete fact-set after quiescence. `skipped.* reason=GATE_BLOCKED`
entries are downstream agents the gate correctly short-circuited; they remain in the trace
for a complete audit log.

---

## TC001 — Wrong Document Uploaded → **BLOCKED** ✅

Two prescriptions submitted for a consultation that requires a prescription **and** a
hospital bill.

**Decision:** `BLOCKED` · confidence `0.95`
**Message:** *"Your CONSULTATION claim requires a HOSPITAL_BILL. The document(s) you uploaded were: PRESCRIPTION, PRESCRIPTION. Please upload a HOSPITAL_BILL."*

The message names the uploaded type **and** the required type — not a generic error, which
is exactly what the case grades. The gate fires, blocks, and 11 downstream agents
short-circuit.

```
#0  submission                 <intake>
#1  verdict.intake             <intake>            conf=1.0
#2  extraction.F002            <extractor.F002>    conf=1.0
#3  verdict.fraud              <velocity_fraud>    conf=1.0
#4  extraction.F001            <extractor.F001>    conf=1.0
#5  member                     <member_resolver>   conf=1.0
#6  gate                       <doc_gate>          conf=1.0   ← blocked: missing HOSPITAL_BILL
#7  skipped.waiting_period     <waiting_period>    reason=GATE_BLOCKED
#8  skipped.exclusion          <exclusion>         reason=GATE_BLOCKED
#9  skipped.policy_reasoner    <policy_reasoner>   reason=GATE_BLOCKED
#10 skipped.document_fraud     <document_fraud>    reason=GATE_BLOCKED
#11 skipped.pre_auth           <pre_auth>          reason=GATE_BLOCKED
#12 skipped.financial_calculator <financial_calculator> reason=GATE_BLOCKED
#13 skipped.semantic_mapper    <semantic_mapper>   reason=GATE_BLOCKED
#14 skipped.cross_validation   <cross_validation>  reason=GATE_BLOCKED
#15 skipped.financial_reconciler <financial_reconciler> reason=GATE_BLOCKED
#16 skipped.prescription_corroboration <prescription_corroboration> reason=GATE_BLOCKED
#17 skipped.per_claim_limit    <per_claim_limit>   reason=GATE_BLOCKED
```

---

## TC002 — Unreadable Document → **BLOCKED** ✅

Valid prescription + an unreadable pharmacy bill.

**Decision:** `BLOCKED` · confidence `0.95`
**Message:** *"The PHARMACY_BILL (blurry_bill.jpg) could not be read. Please re-upload a clear photo of your PHARMACY_BILL."*

Identifies the *specific* document, asks for a re-upload of that document, and does **not**
reject the claim outright — all three case requirements.

```
#0  submission                 <intake>
#1  member                     <member_resolver>   conf=1.0
#2  verdict.fraud              <velocity_fraud>    conf=1.0
#3  verdict.intake             <intake>            conf=1.0
#4  extraction.F004            <extractor.F004>    conf=1.0   ← quality=UNREADABLE
#5  extraction.F003            <extractor.F003>    conf=1.0
#6  gate                       <doc_gate>          conf=1.0   ← blocked: PHARMACY_BILL unreadable
#7–#17  skipped.* (11 downstream agents)           reason=GATE_BLOCKED
```

---

## TC003 — Documents Belong to Different Patients → **BLOCKED** ✅

Prescription for *Rajesh Kumar*, hospital bill for *Arjun Mehta*.

**Decision:** `BLOCKED` · confidence `0.95`
**Messages (two — the collect-all gate surfaces both at once):**
1. *"The HOSPITAL_BILL (bill_arjun.jpg) could not be read clearly — no charges or bill total could be extracted. Please re-upload a clearer photo of the bill."*
2. *"The documents name different patients: the PRESCRIPTION is for 'Rajesh Kumar'; the HOSPITAL_BILL is for 'Arjun Mehta'. All documents for one claim must be for the same person (the member or a covered dependent)."*

The second message names **both** patients found — the case requirement. This case also
demonstrates collect-all: a naive first-fail gate would have stopped at the unusable bill
and never reported the patient mismatch.

```
#0  submission                 <intake>
#1  extraction.F005            <extractor.F005>    conf=1.0   ← patient: Rajesh Kumar
#2  member                     <member_resolver>   conf=1.0
#3  verdict.fraud              <velocity_fraud>    conf=1.0
#4  extraction.F006            <extractor.F006>    conf=1.0   ← patient: Arjun Mehta
#5  verdict.intake             <intake>            conf=1.0
#6  gate                       <doc_gate>          conf=1.0   ← blocked: 2 issues
#7–#17  skipped.* (11 downstream agents)           reason=GATE_BLOCKED
```

---

## TC004 — Clean Consultation → **APPROVED ₹1350** ✅

Complete, valid consultation; everything within limits.

**Decision:** `APPROVED` · amount `₹1350` · confidence `0.95` (> 0.85 bar)
**Note:** *"Gross ₹1500 → no network discount → co-pay 10% on ₹1500 (−₹150) → approved ₹1350."*

Happy path: gate passes, the full roster runs, the waterfall applies the 10% consultation
co-pay. This is the first trace where every downstream agent actually *runs* rather than
skips.

```
#0  submission        <intake>
#1  verdict.fraud     <velocity_fraud>     conf=1.0
#2  member            <member_resolver>    conf=1.0
#3  extraction.F007   <extractor.F007>     conf=1.0
#4  extraction.F008   <extractor.F008>     conf=1.0
#5  verdict.intake    <intake>             conf=1.0
#6  gate              <doc_gate>           conf=1.0   ← passed
#7  verdict.docfraud  <document_fraud>     conf=1.0
#8  semantic          <semantic_mapper>    conf=1.0
#9  verdict.waiting   <waiting_period>     conf=1.0
#10 verdict.preauth   <pre_auth>           conf=1.0
#11 verdict.consistency <cross_validation> conf=1.0
#12 coverage          <exclusion>          conf=1.0
#13 financial_facts   <financial_reconciler> conf=1.0
#14 verdict.prescription <prescription_corroboration> conf=1.0
#15 preliminary_decision <policy_reasoner>
#16 financial_breakdown <financial_calculator> conf=1.0   ← ₹1350
#17 verdict.perclaim  <per_claim_limit>    conf=1.0
#18 policy_reasoning  <policy_reasoner>    conf=1.0
```

---

## TC005 — Waiting Period (Diabetes) → **REJECTED** ✅

Member joined 2024-09-01, claims diabetes treatment 2024-10-15 — inside the 90-day waiting
period.

**Decision:** `REJECTED` · reason `WAITING_PERIOD` · confidence `0.95`
**Message:** *"Treatment for diabetes falls within the 90-day waiting period (member joined 2024-09-01, treated 2024-10-15, 44 days later). The member is eligible for diabetes claims from 2024-11-30."*

States the exact eligibility date (2024-11-30) — the case requirement.

```
#0  submission        <intake>
#1  verdict.intake    <intake>             conf=1.0
#2  extraction.F009   <extractor.F009>     conf=1.0
#3  member            <member_resolver>    conf=1.0   ← join_date 2024-09-01
#4  verdict.fraud     <velocity_fraud>     conf=1.0
#5  extraction.F010   <extractor.F010>     conf=1.0
#6  gate              <doc_gate>           conf=1.0   ← passed
#7  verdict.docfraud  <document_fraud>     conf=1.0
#8  semantic          <semantic_mapper>    conf=1.0
#9  verdict.waiting   <waiting_period>     conf=1.0   ← REJECTED: 44 < 90 days
#10 verdict.preauth   <pre_auth>           conf=1.0
#11 financial_facts   <financial_reconciler> conf=1.0
#12 coverage          <exclusion>          conf=1.0
#13 verdict.consistency <cross_validation> conf=1.0
#14 verdict.prescription <prescription_corroboration> conf=1.0
#15 preliminary_decision <policy_reasoner>
#16 verdict.perclaim  <per_claim_limit>    conf=1.0
#17 policy_reasoning  <policy_reasoner>    conf=1.0
#18 financial_breakdown <financial_calculator> conf=1.0
```

---

## TC006 — Dental Partial (Cosmetic Exclusion) → **PARTIAL ₹8000** ✅

Root canal (covered) + teeth whitening (cosmetic, excluded).

**Decision:** `PARTIAL` · amount `₹8000` · confidence `0.95`
**Message:** *"Approved line items: Root Canal Treatment (₹8000). Excluded line items: Teeth Whitening (₹4000) — Teeth Whitening is excluded under the DENTAL policy."*
**Note:** *"Gross ₹8000 → no network discount → no co-pay → approved ₹8000."*

Itemises which lines were approved/rejected and gives the per-line reason — both case
requirements. The exclusion is a **line-item** exclusion, so the claim proceeds on the
covered line.

```
#0  submission        <intake>
#1  extraction.F011   <extractor.F011>     conf=1.0
#2  verdict.intake    <intake>             conf=1.0
#3  verdict.fraud     <velocity_fraud>     conf=1.0
#4  member            <member_resolver>    conf=1.0
#5  gate              <doc_gate>           conf=1.0   ← passed (dental requires only HOSPITAL_BILL)
#6  semantic          <semantic_mapper>    conf=1.0
#7  verdict.preauth   <pre_auth>           conf=1.0
#8  verdict.docfraud  <document_fraud>     conf=1.0
#9  verdict.waiting   <waiting_period>     conf=1.0
#10 verdict.prescription <prescription_corroboration> conf=1.0
#11 financial_facts   <financial_reconciler> conf=1.0
#12 verdict.consistency <cross_validation> conf=1.0
#13 coverage          <exclusion>          conf=1.0   ← teeth whitening excluded, root canal kept
#14 preliminary_decision <policy_reasoner>
#15 financial_breakdown <financial_calculator> conf=1.0   ← ₹8000
#16 verdict.perclaim  <per_claim_limit>    conf=1.0
#17 policy_reasoning  <policy_reasoner>    conf=1.0
```

---

## TC007 — MRI Without Pre-Authorization → **REJECTED** ✅

₹15,000 MRI; policy requires pre-auth for MRI above ₹10,000.

**Decision:** `REJECTED` · reason `PRE_AUTH_MISSING` · confidence `0.95`
**Message:** *"Pre-authorization is required for MRI above ₹10000 (this claim is ₹15000) and was not obtained. Please obtain pre-authorization from the insurer and resubmit the claim with the pre-auth reference number."*

Explains the requirement and tells the member how to resubmit — both case requirements.

```
#0  submission        <intake>
#1  extraction.F012   <extractor.F012>     conf=1.0   ← prescription: MRI Lumbar Spine
#2  member            <member_resolver>    conf=1.0
#3  verdict.intake    <intake>             conf=1.0
#4  verdict.fraud     <velocity_fraud>     conf=1.0
#5  extraction.F014   <extractor.F014>     conf=1.0   ← bill ₹15000
#6  extraction.F013   <extractor.F013>     conf=1.0   ← lab report
#7  gate              <doc_gate>           conf=1.0   ← passed (all 3 required docs present)
#8  verdict.docfraud  <document_fraud>     conf=1.0
#9  verdict.waiting   <waiting_period>     conf=1.0
#10 semantic          <semantic_mapper>    conf=1.0
#11 verdict.preauth   <pre_auth>           conf=1.0   ← REJECTED: MRI > ₹10000, no pre-auth
#12 financial_facts   <financial_reconciler> conf=1.0
#13 coverage          <exclusion>          conf=1.0
#14 verdict.prescription <prescription_corroboration> conf=1.0
#15 verdict.consistency <cross_validation> conf=1.0
#16 preliminary_decision <policy_reasoner>
#17 financial_breakdown <financial_calculator> conf=1.0
#18 verdict.perclaim  <per_claim_limit>    conf=1.0
#19 policy_reasoning  <policy_reasoner>    conf=1.0
```

---

## TC008 — Per-Claim Limit Exceeded → **REJECTED** ✅

Claimed ₹7,500 exceeds the ₹5,000 per-claim limit.

**Decision:** `REJECTED` · reason `PER_CLAIM_EXCEEDED` · confidence `0.95`
**Message:** *"The covered amount ₹7500 exceeds the per-claim limit of ₹5000. This claim cannot be approved as submitted."*

States both the per-claim limit and the claimed amount — the case requirement. For
consultation, the per-claim limit (₹5,000) ≥ the category sub-limit (₹2,000), so per-claim
is the binding cap and is a hard reject.

```
#0  submission        <intake>
#1  verdict.fraud     <velocity_fraud>     conf=1.0
#2  extraction.F015   <extractor.F015>     conf=1.0
#3  member            <member_resolver>    conf=1.0
#4  extraction.F016   <extractor.F016>     conf=1.0   ← bill ₹7500
#5  verdict.intake    <intake>             conf=1.0
#6  gate              <doc_gate>           conf=1.0   ← passed
#7  verdict.waiting   <waiting_period>     conf=1.0
#8  semantic          <semantic_mapper>    conf=1.0
#9  verdict.docfraud  <document_fraud>     conf=1.0
#10 verdict.preauth   <pre_auth>           conf=1.0
#11 coverage          <exclusion>          conf=1.0   ← covered_amount ₹7500
#12 verdict.prescription <prescription_corroboration> conf=1.0
#13 financial_facts   <financial_reconciler> conf=1.0
#14 verdict.consistency <cross_validation> conf=1.0
#15 preliminary_decision <policy_reasoner>
#16 policy_reasoning  <policy_reasoner>    conf=1.0
#17 financial_breakdown <financial_calculator> conf=1.0
#18 verdict.perclaim  <per_claim_limit>    conf=1.0   ← REJECTED: ₹7500 > ₹5000
```

---

## TC009 — Multiple Same-Day Claims → **MANUAL_REVIEW** ✅

Member EMP008 has 3 prior same-day claims; this is the 4th. Same-day limit is 2.

**Decision:** `MANUAL_REVIEW` · amount `₹4320` (computed for the reviewer) · confidence `0.95`
**Message:** *"Routed to manual review for unusual activity: 4 claims on the same day (2024-10-30) — exceeds the limit of 2."*
**Note:** *"Gross ₹4800 → no network discount → co-pay 10% on ₹4800 (−₹480) → approved ₹4320."*

Flags the specific signal, routes to review rather than auto-rejecting, and includes the
triggering signal in the output — all three case requirements. The payout is still computed
(₹4320) so a human reviewer has the number ready.

```
#0  submission        <intake>
#1  extraction.F017   <extractor.F017>     conf=1.0
#2  verdict.fraud     <velocity_fraud>     conf=1.0   ← MANUAL_REVIEW: 4 same-day > 2
#3  member            <member_resolver>    conf=1.0
#4  extraction.F018   <extractor.F018>     conf=1.0
#5  verdict.intake    <intake>             conf=1.0
#6  gate              <doc_gate>           conf=1.0   ← passed
#7  verdict.waiting   <waiting_period>     conf=1.0
#8  verdict.preauth   <pre_auth>           conf=1.0
#9  semantic          <semantic_mapper>    conf=1.0
#10 verdict.docfraud  <document_fraud>     conf=1.0
#11 coverage          <exclusion>          conf=1.0
#12 financial_facts   <financial_reconciler> conf=1.0
#13 verdict.prescription <prescription_corroboration> conf=1.0
#14 verdict.consistency <cross_validation> conf=1.0
#15 preliminary_decision <policy_reasoner>
#16 financial_breakdown <financial_calculator> conf=1.0   ← ₹4320
#17 verdict.perclaim  <per_claim_limit>    conf=1.0
#18 policy_reasoning  <policy_reasoner>    conf=1.0
```

---

## TC010 — Network Hospital Discount → **APPROVED ₹3240** ✅

Apollo Hospitals (network). Discount must be applied **before** co-pay.

**Decision:** `APPROVED` · amount `₹3240` · confidence `0.95`
**Note:** *"Gross ₹4500 → network discount 20% (−₹900) → co-pay 10% on ₹3600 (−₹360) → approved ₹3240."*

The order is correct and visible in the note: 20% discount on ₹4,500 → ₹3,600, then 10%
co-pay on ₹3,600 → ₹3,240. Applying co-pay first would give a different number; the engine
gets the assignment's exact value.

```
#0  submission        <intake>
#1  extraction.F019   <extractor.F019>     conf=1.0
#2  verdict.fraud     <velocity_fraud>     conf=1.0
#3  member            <member_resolver>    conf=1.0
#4  extraction.F020   <extractor.F020>     conf=1.0   ← hospital: Apollo Hospitals
#5  verdict.intake    <intake>             conf=1.0
#6  gate              <doc_gate>           conf=1.0   ← passed
#7  verdict.waiting   <waiting_period>     conf=1.0
#8  verdict.preauth   <pre_auth>           conf=1.0
#9  verdict.docfraud  <document_fraud>     conf=1.0
#10 semantic          <semantic_mapper>    conf=1.0
#11 verdict.prescription <prescription_corroboration> conf=1.0
#12 verdict.consistency <cross_validation> conf=1.0
#13 coverage          <exclusion>          conf=1.0
#14 financial_facts   <financial_reconciler> conf=1.0
#15 preliminary_decision <policy_reasoner>
#16 policy_reasoning  <policy_reasoner>    conf=1.0
#17 verdict.perclaim  <per_claim_limit>    conf=1.0
#18 financial_breakdown <financial_calculator> conf=1.0   ← discount before co-pay → ₹3240
```

---

## TC011 — Component Failure (Graceful Degradation) → **APPROVED** ✅

`simulate_component_failure: true` makes `DocumentFraudAgent` raise mid-run.

**Decision:** `APPROVED` · amount `₹4000` · confidence **`0.70`** (lowered from 0.95)
**Notes:**
1. *"Gross ₹4000 → no network discount → no co-pay → approved ₹4000."*
2. *"⚠ A component (document_fraud) failed during processing and was skipped. The decision was made on the remaining checks; manual review is recommended due to incomplete processing."*

All four case requirements met: no crash/500, the failure is visible in the output, the
confidence is lower than a normal approval (0.70 = 0.95 − 0.25 degradation penalty), and a
manual-review note is included. Note fact `#7` carries the `[DEGRADED]` marker — the failed
agent is *recorded* in the trace, not silently dropped.

```
#0  submission        <intake>
#1  extraction.F021   <extractor.F021>     conf=1.0
#2  verdict.intake    <intake>             conf=1.0
#3  extraction.F022   <extractor.F022>     conf=1.0
#4  verdict.fraud     <velocity_fraud>     conf=1.0
#5  member            <member_resolver>    conf=1.0
#6  gate              <doc_gate>           conf=1.0   ← passed
#7  verdict.docfraud  <document_fraud>     [DEGRADED]  ← raised; contained to a degraded fact
#8  verdict.waiting   <waiting_period>     conf=1.0
#9  semantic          <semantic_mapper>    conf=1.0
#10 verdict.preauth   <pre_auth>           conf=1.0
#11 verdict.prescription <prescription_corroboration> conf=1.0
#12 verdict.consistency <cross_validation> conf=1.0
#13 financial_facts   <financial_reconciler> conf=1.0
#14 coverage          <exclusion>          conf=1.0
#15 preliminary_decision <policy_reasoner>
#16 verdict.perclaim  <per_claim_limit>    conf=1.0
#17 financial_breakdown <financial_calculator> conf=1.0   ← ₹4000
#18 policy_reasoning  <policy_reasoner>    conf=1.0
```

---

## TC012 — Excluded Treatment (Bariatric) → **REJECTED** ✅

Bariatric consultation + diet program; obesity treatment is explicitly excluded.

**Decision:** `REJECTED` · reason `EXCLUDED_CONDITION` · confidence `0.95` (> 0.90 bar)
**Message:** *"This claim is for an excluded condition (matched policy exclusion term: bariatric, obesity). Such treatments are not covered."*

A **whole-claim** exclusion (matched both "bariatric" and "obesity" from
`exclusions.conditions`), so every line is excluded and the claim is rejected outright —
distinct from TC006's line-item exclusion.

```
#0  submission        <intake>
#1  extraction.F023   <extractor.F023>     conf=1.0   ← diagnosis: Morbid Obesity; Bariatric
#2  verdict.intake    <intake>             conf=1.0
#3  member            <member_resolver>    conf=1.0
#4  extraction.F024   <extractor.F024>     conf=1.0
#5  verdict.fraud     <velocity_fraud>     conf=1.0
#6  gate              <doc_gate>           conf=1.0   ← passed
#7  semantic          <semantic_mapper>    conf=1.0
#8  verdict.docfraud  <document_fraud>     conf=1.0
#9  verdict.waiting   <waiting_period>     conf=1.0
#10 verdict.preauth   <pre_auth>           conf=1.0
#11 financial_facts   <financial_reconciler> conf=1.0
#12 coverage          <exclusion>          conf=1.0   ← whole_claim_excluded: bariatric, obesity
#13 verdict.prescription <prescription_corroboration> conf=1.0
#14 verdict.consistency <cross_validation> conf=1.0
#15 preliminary_decision <policy_reasoner>
#16 verdict.perclaim  <per_claim_limit>    conf=1.0
#17 financial_breakdown <financial_calculator> conf=1.0
#18 policy_reasoning  <policy_reasoner>    conf=1.0
```

---

## Where it didn't match

Nothing. All 12 cases matched the expected outcome on every graded dimension — status,
approved amount, ranked rejection reasons, confidence thresholds, and the
message-quality substrings. The `pytest tests/eval/` floor (`EXPECTED_GREEN = 12`) enforces
this in CI, so any regression that turns a green case red fails the build.
