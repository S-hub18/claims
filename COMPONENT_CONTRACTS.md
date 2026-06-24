# Component Contracts — Claims Adjudication

*For every significant component: what it accepts, what it produces, and what it can
raise. Precise enough to reimplement any single component without reading its code.*

A note on the universal substrate: nearly every engine component communicates **only**
through the blackboard. So most contracts are expressed as **fact keys read** and the
**one fact key written**. The shared fact schema is defined once, in §1.

---

## 1. `Fact` — the universal message (`blackboard/core.py`)

Immutable, frozen dataclass. Every agent output and the submission seed are Facts.

| Field | Type | Meaning |
|---|---|---|
| `key` | `str` | Unique-ish fact name. `verdict.*`, `extraction.<id>`, `coverage`, etc. |
| `value` | `Any` | The payload (always a JSON-serialisable dict in practice). |
| `author` | `str` | The agent `name` that posted it. |
| `seq` | `int` | Monotonic per-claim sequence. Assigned by `Blackboard.post()`; agents leave `-1`. |
| `confidence` | `float \| None` | Per-fact confidence in `[0,1]`; `None` if N/A. |
| `degraded` | `bool` | `True` if produced by a failed/timed-out component. |
| `derived_from` | `tuple[str,...]` | Lineage; auto-set from the posting agent's `reads`. |
| `policy_version_id` | `str \| None` | Policy version stamp (optional). |
| `reason` | `str \| None` | Skip reason: `PROVABLY_PASS \| GATE_BLOCKED \| GUARD_FIRED \| TIMEOUT`. |

**Errors:** none — construction is total. `seq`/`derived_from` are overwritten on `post()`.

---

## 2. `Blackboard` — the fact store (`blackboard/core.py`)

| Method | Input | Output | Notes |
|---|---|---|---|
| `post(fact, agent=None)` | a `Fact`, optional posting `Agent` | the stored `Fact` (with `seq` + lineage) | Mutates store; assigns `seq`, derives `derived_from` from `agent.reads`. |
| `has(key)` | `str` | `bool` | Exact-key existence. |
| `has_prefix(prefix)` | `str` | `bool` | Any key starts with prefix (e.g. `extraction.`). |
| `get(key)` | `str` | `Fact \| None` | Latest fact for key, or `None`. |
| `all()` | — | `list[Fact]` | Canonical order by `seq` — the replayable trace. |
| `keys()` | — | `list[str]` | All posted keys. |
| `skipped()` | — | `dict[str,str]` | agent-name → skip reason, from `skipped.*` facts. |

**Errors:** none raised; missing keys return `None`/`False`.

---

## 3. `Agent` — the base contract (`blackboard/core.py`)

A subclass sets three class attributes and implements one coroutine.

| Member | Type | Contract |
|---|---|---|
| `name` | `str` | Unique agent id; becomes `author` and the `skipped.<name>` key. |
| `reads` | `list[str]` | Fact keys this agent depends on. Drives scheduling **and** lineage. |
| `writes` | `str` | The single fact key this agent produces. |
| `ready(bb)` | `(Blackboard) → AgentState` | `READY` when all `reads` exist (default); override for custom gating. Returns `WAIT` / `READY` / `SKIP`. |
| `skip_reason(bb)` | `(Blackboard) → str` | Reason string when `ready()` returns `SKIP`. Default `PROVABLY_PASS`. |
| `run(bb)` | `(Blackboard) → Fact` | **Safe** entry point the scheduler calls. Wraps `_run`; **never raises** — on any exception returns a `degraded` Fact keyed `writes` (or `<name>.error`). |
| `_run(bb)` | `(Blackboard) → Fact` | The actual work. May raise; `run()` contains it. |

**`GateGatedAgent`** subclass: overrides `ready()` to `WAIT` until the `gate` fact exists,
`SKIP` (reason `GATE_BLOCKED`) if the gate blocked, else defer to the normal reads check.
Every downstream rule/financial agent inherits this.

**`AgentState`** enum: `WAIT` (poll again), `READY` (fire now), `SKIP` (prune + post a
skip fact).

---

## 4. `adjudicate()` — the scheduler (`blackboard/scheduler.py`)

```python
async def adjudicate(submission, agents, timeout_s=120.0, on_post=None) -> Blackboard
```

| Input | Type | Meaning |
|---|---|---|
| `submission` | `Any` (dict) | The claim; posted as fact #0 keyed `submission`. |
| `agents` | `Iterable[Agent]` | The roster to run to quiescence. |
| `timeout_s` | `float` | Wall-clock deadline; stragglers drained as `TIMEOUT` degraded facts. |
| `on_post` | `Callable[[Fact], None] \| None` | Hook fired for **every** posted fact (SSE / DB seam). |

**Output:** the populated `Blackboard` once quiescent (nothing running, nothing newly
ready) or the deadline hit.

**Behaviour:** each tick fires all `READY` agents concurrently as `asyncio` tasks, posts
`skipped.*` for `SKIP` agents, awaits `FIRST_COMPLETED`, posts results. **Errors:** does
not raise on agent failure (agents self-contain via `run()`); on timeout it cancels
running tasks and returns the partial board.

---

## 5. `Policy` — policy loader (`policy/loader.py`)

Policy is **data**, loaded from `policy_terms.json`. No threshold is embedded in code.

| Method | Input | Output | Raises |
|---|---|---|---|
| `from_file(path)` | path | `Policy` | `FileNotFoundError`, `json.JSONDecodeError` |
| `get(path, default=…)` | dotted path e.g. `coverage.per_claim_limit` | the value | `KeyError` if missing **and** no default (typos fail loud) |
| `version_id` | — | `str` | — |
| `category(cat)` | category name | `dict` | `KeyError` if category absent |
| `required_documents(cat)` | category | `list[str]` | `KeyError` |
| `optional_documents(cat)` | category | `list[str]` | — (defaults `[]`) |
| `per_claim_limit()` | — | number | `KeyError` |
| `waiting_period_days(cond)` | condition | number `\| None` | — |
| `network_hospitals()` | — | `list[str]` | — |
| `is_network_hospital(name)` | name `\| None` | `bool` | — (exact / substring / reverse match) |
| `min_claim_amount()` | — | number | `KeyError` |
| `fraud(key)` | threshold key | value | `KeyError` |
| `members()` / `member(id)` | — / id | `list` / `dict \| None` | — |

---

## 6. `LLMClient` protocol + `ExtractionResult` (`llm/base.py`)

The vendor-agnostic seam. Implementations: `AnthropicClient` (primary), `GeminiClient`
(fallback), `FakeLLMClient` (offline/tests).

```python
class LLMClient(Protocol):
    async def extract(file_id, data: bytes, mime_type="image/jpeg",
                      hint_type: str|None=None) -> ExtractionResult
```

**`ExtractionResult`** (dataclass) — maps 1:1 to the `extraction.<id>` fact value:

| Field | Type | Default |
|---|---|---|
| `file_id` | `str` | — |
| `doc_type` | `str \| None` | `None` (`PRESCRIPTION` \| `HOSPITAL_BILL` \| …) |
| `readable` | `bool` | `True` |
| `quality` | `str` | `"GOOD"` (`GOOD` \| `POOR` \| `UNREADABLE`) |
| `patient_name` / `doctor_name` / `doctor_registration` / `hospital_name` | `str \| None` | `None` |
| `date` | `str \| None` | `None` (`YYYY-MM-DD`) |
| `diagnosis` / `treatment` | `str \| None` | `None` |
| `medicines` / `tests_ordered` | `list[str]` | `[]` |
| `line_items` | `list[dict]` | `[]` (`{description, amount}`) |
| `total_amount` | `float \| None` | `None` |
| `confidence` | `float` | `1.0` |
| `raw` | `dict` | `{}` (full LLM JSON for tracing) |

**Reasoning-capable clients** additionally expose `reason(prompt, tool_declarations,
tool_executor, response_schema, on_tool_call)` and `reason_simple(prompt, schema)`, used
by the policy reasoner. **Errors:** live clients may raise an exception carrying a `.kind`
attribute (`QUOTA` / `NETWORK` / `SERVER`); `DocExtractor` catches it and emits a
`system_error` fact (see §8).

---

## 7. `FakeLLMClient` (`llm/fake.py`)

| Method | Input | Output |
|---|---|---|
| `register(file_id, doc)` | id, raw test-case doc dict | `None` (stores inline content) |
| `extract(file_id, data, …)` | id, bytes (ignored) | `ExtractionResult` lifted from the registered inline `content` |

Deterministic, zero network. **Errors:** none — an unregistered id yields an empty result.

---

## 8. Agents — read/write contracts

Every agent below writes exactly one fact. Inputs are **fact keys** unless noted. All
inherit the `Agent.run()` guarantee: failure → a `degraded` fact, never an exception.

### `MemberResolver` (`member_resolver.py`)
- **reads** `submission` → **writes** `member`
- **value (found):** `{found: true, record: {…}, dependents: [{…}]}`
- **value (not found):** `{found: false, member_id}`
- Resolves the member and covered dependents from the policy roster.

### `IntakeValidator` (`intake.py`)
- **reads** `submission` → **writes** `verdict.intake`
- **value:** `{status: "PASS"}` or `{status:"REJECTED", reason:"BELOW_MIN_AMOUNT", message}`
- Enforces the minimum claim amount. (Submission-deadline check intentionally disabled — test dates are historical.)

### `DocExtractor` (`extractor.py`) — one instance per document
- **reads** `submission` → **writes** `extraction.<file_id>`
- **value (normal):** `{file_id, doc_type, readable, quality, patient_name, content:{doctor_name, doctor_registration, hospital_name, patient_name, date, diagnosis, treatment, medicines, tests_ordered, line_items, total}}`
- **value (system error):** `{file_id, system_error:true, error_kind, message, readable:null}` (degraded)
- Three paths: live LLM (real bytes), Fake (inline content via `register`), pure offline (lift inline `content`). Charge-bearing docs are retyped to `HOSPITAL_BILL` regardless of model label.

### `DocGate` (`doc_gate.py`)
- **reads** `submission`, `member`, all `extraction.<id>` → **writes** `gate`
- Custom `ready()`: waits until member resolved **and** every document extracted.
- **value:** `{blocked: bool, issues: [str], present_types: [str], required: [str]}`
- **Collect-all** — runs three checks and accumulates *all* issues: (1) readability + usable-bill, (2) required document types present, (3) single-patient + covered. Always posts `gate` (blocked or not).

### `SemanticMapper` (`semantic.py`, gate-gated)
- **reads** `submission` (+ extractions) → **writes** `semantic`
- **value:** `{category, category_covered, lines:[{description, amount, kind, excluded:false, reason:null}], bill_total}`
- Normalises the bill into classified line items; tags the consultation-fee line.

### `ExclusionAgent` (`exclusion.py`, gate-gated)
- **reads** `semantic` (+ extractions) → **writes** `coverage`
- **value:** `{category, lines:[…], covered_amount, covered_count, excluded_count, whole_claim_excluded, matched_terms, message}`
- Two layers: whole-claim exclusion (`exclusions.conditions` keyword match → all lines excluded) and line-item exclusion (`opd_categories[cat].excluded_*`). Keywords derived from policy phrases (≥5 chars, non-stopword).

### `FinancialReconciler` (`financial.py`, gate-gated)
- **reads** `semantic` → **writes** `financial_facts`
- **value:** `{line_sum, bill_total, divergence: bool}` — flags Σ(lines) ≠ stated total.

### `FinancialCalculator` (`financial.py`, gate-gated)
- **reads** `coverage`, `financial_facts`, `submission` → **writes** `financial_breakdown`
- **value:** `{approved_amount, gross, network_discount:{pct,amount}, copay:{pct,amount}, sub_limit_cap_applied, currency:"INR", note}`
- **Waterfall (order is the contract):** gross (covered lines, consultation-fee line capped at sub-limit) → **− network discount** → **− co-pay** → category cap. `Decimal`, `ROUND_HALF_UP`.

### `WaitingPeriodAgent` (`rules.py`, gate-gated)
- **reads** `submission`, `member` → **writes** `verdict.waiting`
- **value:** `{status:"PASS"}` or `{status:"REJECTED", reason:"WAITING_PERIOD", message}` (message states the eligibility date).
- Matches a condition only when *every* significant token of the policy key appears as a whole word.

### `PreAuthAgent` (`rules.py`, gate-gated)
- **reads** `submission` (+ extractions) → **writes** `verdict.preauth`
- **value:** `{status:"PASS"}` or `{status:"REJECTED", reason:"PRE_AUTH_MISSING", message}`
- Rejects a high-value test (`high_value_tests_requiring_pre_auth`) over `pre_auth_threshold` submitted without pre-auth.

### `PerClaimLimitAgent` (`rules.py`, gate-gated)
- **reads** `coverage` → **writes** `verdict.perclaim`
- **value:** `{status:"PASS", binding_ceiling}` or `{status:"REJECTED", reason:"PER_CLAIM_EXCEEDED", message}`
- Per-claim is a hard reject only when it is the **binding** cap (≥ category sub-limit); otherwise the calculator caps instead.

### `VelocityFraudAgent` (`fraud.py`, **not** gate-gated)
- **reads** `submission` → **writes** `verdict.fraud`
- **value:** `{status:"PASS"}` or `{status:"MANUAL_REVIEW", reason:"FRAUD_FLAG", message, signals:[str]}`
- Same-day / monthly velocity + high-value threshold from the claim's *inline* `claims_history`. Fires at intake (needs no documents).

### `DocumentFraudAgent` (`fraud.py`, gate-gated)
- **reads** `submission` → **writes** `verdict.docfraud`
- **value:** `{status:"PASS"}`; **raises** `RuntimeError` when `simulate_component_failure` is set → `run()` posts a `degraded` fact (TC011's injectable fault).

### `CrossValidationAgent` (`cross_validation.py`, gate-gated)
- **reads** `semantic` (+ extractions, submission) → **writes** `verdict.consistency`
- **value:** `{status:"PASS"}` or `{status:"MANUAL_REVIEW", reason:"DETAILS_MISMATCH", message, discrepancies:[str]}`
- Claimed amount vs bill total (1% tolerance) + treatment date vs document dates (±3 days). Soft signal — never changes the amount.

### `PrescriptionCorroborationAgent` (`prescription_check.py`, gate-gated)
- **reads** `semantic` (+ extractions) → **writes** `verdict.prescription`
- **value:** `{status:"PASS"|"MANUAL_REVIEW", reason, message, unsupported_items?, prescribed?}`
- Flags a *specific* billed medicine (carries dosage/form marker) not corroborated by the prescription. Conservative soft signal.

### `PolicyReasonerAgent` (`policy_reasoner.py`, gate-gated, LangGraph)
- **reads** `coverage` → **writes** `policy_reasoning` (+ side facts)
- **Side facts posted during the run:** `preliminary_decision` (immediate keyword answer), `policy_reasoning.step` (one per reasoning step, streamed), and on outcome either `coverage.revised` (OVERRIDE) or `flag.ambiguity` (ESCALATE → MANUAL_REVIEW).
- **`policy_reasoning` value:** `{verdict: "CONFIRM"|"OVERRIDE"|"ESCALATE", confidence, iterations, rationale, tool_calls:[…]}`
- Offline / no reasoning LLM → immediate `CONFIRM`. Any internal failure → `degraded` `CONFIRM` (keyword baseline stands). ≤3 verification passes (`MAX_ITERS`); decides at `confidence ≥ 0.75`.

---

## 9. `DecisionAggregator` → `Decision` (`aggregator.py`, `decision.py`)

```python
DecisionAggregator(policy).decide(bb: Blackboard) -> Decision
```

- **Input:** a quiescent `Blackboard`.
- **Output:** a `Decision`. **Errors:** none — total over any fact-set.

**`Decision`** dataclass:

| Field | Type | Notes |
|---|---|---|
| `status` | `str` | `BLOCKED \| REJECTED \| MANUAL_REVIEW \| PARTIAL \| APPROVED \| PROCESSING_ERROR` |
| `approved_amount` | `Decimal \| None` | Set for APPROVED / PARTIAL / (computed-for) MANUAL_REVIEW |
| `rejection_reasons` | `list[str]` | Ranked; primary first |
| `messages` | `list[str]` | Member-facing explanations |
| `notes` | `list[str]` | Waterfall note + degradation overlay |
| `confidence` | `float \| None` | `0.95 × min(extraction_q, rule_q) − 0.25 × degraded`, clamped |
| `trace` | `list[Fact]` | The full ordered fact-set |

Precedence ladder and confidence formula are specified in **ARCHITECTURE.md §6**.

---

## 10. Engine entry points (`engine.py`)

| Function | Input | Output |
|---|---|---|
| `build_agents(policy, submission, llm_client=None, on_post=None)` | policy, submission dict, optional LLM, optional hook | `list[Agent]` — the roster, with one `DocExtractor` per document |
| `run_claim(submission, policy, llm_client=None, on_post=None)` | as above | `Decision` (awaitable) |

`run_claim` = `adjudicate(...)` to quiescence, then `DecisionAggregator(policy).decide(bb)`.
**Errors:** does not raise for claim-logic failures; surfaces them as `degraded` facts and a
status. (Infra exceptions inside the API are caught one layer up — §11.)

---

## 11. HTTP API (`api/main.py`, `api/routes/claims.py`, `api/schemas.py`)

| Endpoint | Request | Response | Errors |
|---|---|---|---|
| `POST /claims` | `ClaimSubmission` (JSON) | `202` `{claim_id, status:"processing"}` in ms | validation `422`; never a raw `5xx` (global handler returns a JSON envelope) |
| `GET /claims/{id}` | path id | `DecisionResponse` (status, amount, reasons, messages, notes, confidence, `facts[]` once settled) | `404` if unknown |
| `GET /claims/{id}/stream` | path id | `text/event-stream` — one `event: fact` per posted fact, then `event: decision` | `404` if unknown |
| `GET /health` | — | `{status:"ok", db, redis}` | — |

**`ClaimSubmission`** (input): `member_id, policy_id, claim_category, treatment_date,
claimed_amount, hospital_name?, client_session?, ytd_claims_amount?, claims_history[],
simulate_component_failure, documents[], policy_override?`. `DocumentInput` carries either
inline `content` (demo/test) or base64 `data` (real upload). `to_engine_dict()` flattens
to the engine's submission dict, base64-decoding `data` to bytes.

**Contract guarantees:** adjudication runs as a `BackgroundTask`; `POST` returns
immediately. SSE replays already-posted facts to late/reconnecting clients before
streaming live ones. The API **never** returns a raw 5xx — the global exception handler
wraps any error in `{error, type}`.

---

## 12. `ClaimStore` (`api/store.py`)

The state seam — injected with optional Redis + Postgres; defaults to in-memory.

| Method | Purpose |
|---|---|
| `create(claim_id)` / `get(id)` / `get_or_load(id)` | lifecycle; `get_or_load` falls back to DB on a memory miss |
| `on_post_hook(record)` | returns the `on_post` callback the engine calls per fact (appends + publishes to SSE) |
| `finish(record, decision)` / `fail(record, msg)` | settle a claim |
| `persist(record)` | bulk-write facts + decision to DB (no-op without `DATABASE_URL`) |
| `ledger_history(key)` / `record_in_ledger(key, date, amount)` | per-`(session,member)` velocity ledger for the live custom flow |

**Errors:** designed to degrade — a DB/Redis miss falls back to in-memory rather than
failing the claim.
