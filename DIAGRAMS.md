# System Diagrams

---

## 1. End-to-End Claim Processing Pipeline

```mermaid
flowchart TD
    START([Member Submits Claim]) --> S1

    S1[Stage 1: Intake Validation]
    S1 -->|member not found| STOP1([STOP: member not on policy])
    S1 -->|amount below minimum| STOP2([STOP: below minimum claimable amount])
    S1 --> S2

    S2[Stage 2: Document Extraction\nDocuments extracted in PARALLEL\nEach result streamed live via SSE]
    S2 --> S3

    S3[Stage 3: Document Verification Gate\nCollect-all — report once]
    S3 -->|issues found| STOP3([STOP: all N problems listed\nin one message — fix and resubmit])
    S3 --> S4

    S4[Stage 4: Semantic Mapping\ndiagnosis to waiting condition\ntreatment to exclusion candidates\nhigh-value test detection]
    S4 --> S5

    S5[Stage 5: Policy Rule Checks\nwaiting period · exclusions · pre-auth\nlimits · fraud velocity · doc anomaly]
    S5 --> S6

    S6[Stage 6: Financial Calculation\nnetwork discount then co-pay then sub-limit cap]
    S6 --> S7

    S7[Stage 7: Decision Aggregation\nAPPROVED · PARTIAL · REJECTED · MANUAL_REVIEW]
    S7 --> S8

    S8[Stage 8: Verify and Explain\nindependent evidence check\nconfidence score · full trace]
    S8 --> END([Decision delivered to member])
```

---

## 2. Document Verification Gate — Collect-All Logic

```mermaid
flowchart TD
    START([All documents extracted]) --> LOOP

    LOOP[For each document]

    LOOP --> R{Unreadable?}
    R -->|yes| A1[Add issue: re-upload this doc\nSKIP type and patient checks\nfor this document]
    R -->|no| T

    T{Correct type for category?}
    T -->|missing required type| A2[Add issue: name what was\nuploaded and what is needed]
    T -->|out-of-category type| A3[Add issue: this doc type\nis not used for this claim]
    T -->|correct| P

    P{Patient matches member\nor covered dependent?}
    P -->|mismatch| A4[Add issue: patient mismatch\nname both conflicting values]
    P -->|match| F

    F{Critical field missing?}
    F -->|yes| A5[Add issue: ask member\nto supply the field]
    F -->|no| OK[No issue for this doc]

    A1 & A2 & A3 & A4 & A5 & OK --> NEXT{More docs?}
    NEXT -->|yes| LOOP
    NEXT -->|no| CHECK

    CHECK{Issues list empty?}
    CHECK -->|yes| PROCEED([Proceed to adjudication])
    CHECK -->|no| REPORT([STOP: emit all issues\nin one consolidated message])
```

---

## 3. Real-Time Member Experience — SSE Streaming

```mermaid
sequenceDiagram
    participant M as Member
    participant API as Backend API
    participant EXT as Doc Extractors parallel
    participant GATE as Gate
    participant ADJ as Adjudication Engine

    M->>API: Submit claim and documents
    API-->>M: SSE stream opened

    par Parallel extraction
        API->>EXT: Extract doc 1
        API->>EXT: Extract doc 2
        API->>EXT: Extract doc 3
    end

    EXT-->>M: SSE: Doc 1 of 3 — Prescription identified
    EXT-->>M: SSE: Doc 2 of 3 — Bill unreadable
    EXT-->>M: SSE: Doc 3 of 3 — Lab report identified

    EXT->>GATE: All extraction results

    alt Gate finds issues
        GATE-->>M: SSE: BLOCKED — re-upload your bill, it could not be read
    else Gate passes
        GATE->>ADJ: Begin adjudication
        ADJ-->>M: SSE: Checking policy rules
        ADJ-->>M: SSE: Checking financials
        ADJ-->>M: SSE: Decision — APPROVED with full trace
    end
```

---

## 4. Financial Calculation — Order Is Load-Bearing

```mermaid
flowchart LR
    A([Covered lines after exclusions]) --> B[gross = sum of covered lines]
    B --> RC{Line items sum\nto bill total?}
    RC -->|diverge| D[use sum of line items\nflag discrepancy as anomaly]
    RC -->|match| E[use gross as-is]
    D & E --> F{Hospital in network?}
    F -->|yes| G[apply network_discount_percent\npost_discount = gross minus discount]
    F -->|no| H[no discount\npost_discount = gross]
    G & H --> I[apply copay_percent\napproved = post_discount minus copay]
    I --> J[apply sub-limit cap from policy category]
    J --> K([approved_amount])
```

---

## 5. Decision Precedence

```mermaid
flowchart TD
    START([All verdicts collected]) --> D1

    D1{Document problem\ndetected at gate?}
    D1 -->|yes| BLOCKED([BLOCKED\nTC001 TC002 TC003])
    D1 -->|no| D2

    D2{Any definitive\npolicy violation?}
    D2 -->|yes| REJECTED([REJECTED\nreason rank: exclusion then waiting\nthen pre-auth then per-claim\nTC005 TC007 TC008 TC012])
    D2 -->|no| D3

    D3{Fraud FLAG or\nhigh-value or low confidence?}
    D3 -->|yes| MANUAL([MANUAL_REVIEW\nTC009])
    D3 -->|no| D4

    D4{All covered lines excluded\ncovered equals zero?}
    D4 -->|yes| REJECTED2([REJECTED not PARTIAL zero])
    D4 -->|no| D5

    D5{Some lines excluded\nat least one approved?}
    D5 -->|yes| PARTIAL([PARTIAL\nTC006])
    D5 -->|no| APPROVED([APPROVED\nTC004 TC010 TC011])

    COMP([Component failure at any stage\noverlay: keep status\nadd manual review note\nlower confidence — TC011])
```

---

## 6. Fraud Detection — Two Tracks

```mermaid
flowchart TD
    SUB([Claim submitted]) --> T1 & T2

    subgraph T1 [Track 1 — Velocity runs at intake]
        V1{Same-day count\nexceeds policy limit?}
        V2{Monthly count\nexceeds policy limit?}
        V3{Amount above\nauto-review threshold?}
        V1 & V2 & V3 -->|any yes| FLAG1[FLAG]
    end

    subgraph T2 [Track 2 — Doc anomaly runs after extraction]
        DA1[Signals: altered amounts\nconflicting stamps\nline items not summing\nmismatched dates]
        DA1 --> SCORE{Fraud score above\npolicy threshold?}
        SCORE -->|yes| FLAG2[FLAG]
    end

    FLAG1 & FLAG2 --> COMBINE[Combine flags]
    COMBINE --> PREC{Definitive rejection\nalready present?}
    PREC -->|yes| KEEP([Keep REJECTED\nrecord fraud signals in trace])
    PREC -->|no| ESCALATE([Escalate to MANUAL_REVIEW])
```

---

## 7. Chosen Architecture — Multi-Agent Blackboard (B-static)

Agents fire the instant their input facts exist — no phases, no barriers. Instant-evidence verdicts land at t≈0; confidence-sensitive verdicts wait for the self-corrected extraction. Each agent fires at most once (B-static: no re-firing).

```mermaid
flowchart TD
    SUB([submission posted to board])
    DOCS([documents posted to board])

    SUB --> MEM[MemberResolver]
    SUB --> PCL[PerClaimLimitAgent\nINSTANT - TC008]
    SUB --> HV[HighValueAgent\nINSTANT]
    MEM --> VEL[VelocityFraudAgent\nreads claims ledger\nINSTANT - TC009]

    DOCS --> DET[DocDetector per file]
    DET --> EXT[Extractor per segment\nself-corrects before posting]
    EXT --> GATE{DocGate - COLLECT ALL\nreport every problem once\nTC001 TC002 TC003}
    GATE -->|blocked| STOP([STOP: all issues in one message])
    GATE -->|passed| FACTS

    subgraph FACTS [Synthesis facts - fire as extraction lands]
        SM[SemanticMapper]
        PR[PatientResolver]
        FR[FinancialReconciler]
        CC[ClinicalChainAgent\nedge: coherence reference lacks]
    end

    SM --> WP[WaitingPeriodAgent\nTC005]
    CC --> EXC[ExclusionAgent\nTC006 TC012]
    FR --> PA[PreAuthAgent\nTC007]
    MEM --> AGL[AggregateLimitsAgent]
    PR --> DF[DocumentFraudAgent]
    CC --> DF

    WP & EXC & PA & AGL & DF & PCL & HV & VEL --> FC[FinancialCalculator\ndiscount then copay then cap\nTC010]
    FR --> FC
    FC --> DEC[DecisionAggregator\nprecedence: PRD section 5]
    DEC --> VER[Verifier - async\nmay escalate to MANUAL_REVIEW]
    DEC --> OUT([decision streamed to UI])

    GUARD[Adaptive guards: an agent resolves to a SKIP fact\ninstead of firing when it provably PASSes\ne.g. pre_auth on non-diagnostic category]
    GUARD -.governs.-> PA
    GUARD -.governs.-> WP
```

---

## 8. Why the Blackboard Beats a Phased DAG (speed + confidence at once)

```mermaid
flowchart LR
    subgraph DAG [Phased DAG - one global speed/confidence choice]
        A1[extract all] --> B1[barrier] --> C1[all rules] --> D1[decision]
    end

    subgraph BB [Blackboard - per-agent tolerance]
        I1[per-claim limit\nzero extraction confidence needed] --> R1([fires at t=0])
        I2[exclusion check\nexquisitely confidence-sensitive] --> R2([waits for corrected extraction])
    end

    NOTE[Same claim: instant checks answer immediately\nwhile confidence-sensitive checks wait\nfor the high-confidence fact]
    BB --- NOTE
```
