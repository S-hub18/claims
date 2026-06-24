"use client";

import { useState } from "react";
import type { EngineProps } from "./ui";
import { Select, STATUS_COLORS, statusLabel } from "./ui";
import { DocPreview } from "./DocPreview";
import { fmt, iconFor } from "@/lib/format";
import { CATEGORY_OPTIONS } from "@/lib/api";
import type { EmployeeDocument } from "@/lib/db";
import type { Status, TraceFact } from "@/lib/types";

// ── fact → plain English ──────────────────────────────────────────────────────
// The lifecycle view replays the engine's own trace. Every agent posts a fact; this
// turns each one into a readable step and pulls out any issue it raised, so two
// problems (e.g. a date mismatch AND a wrong patient) both show — not just the one
// the final decision happened to lead with.

type Tone = "ok" | "warn" | "bad" | "muted" | "info";

const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--st-approved)",
  warn: "var(--st-manual)",
  bad: "var(--st-rejected)",
  muted: "var(--muted)",
  info: "var(--primary)",
};

const TONE_VERDICT: Record<Tone, string> = {
  ok: "✓ pass",
  warn: "⚠ review",
  bad: "✕ fail",
  muted: "skipped",
  info: "logged",
};

// Two-letter code shown inside each timeline node — a console-ish marker per phase.
const PHASE_CODE: Record<string, string> = {
  Intake: "IN",
  Identity: "ID",
  Extraction: "EX",
  "Document gate": "GT",
  Coverage: "CV",
  "Rules & limits": "RL",
  "Fraud & integrity": "FR",
  Consistency: "CS",
  Financial: "₹",
  Reasoning: "AI",
  Skipped: "··",
  Other: "•",
};

interface Step {
  phase: string;
  title: string;
  detail: string;
  tone: Tone;
  issues: string[];
}

function asObj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

function statusTone(status: unknown, degraded?: boolean): Tone {
  if (degraded) return "bad";
  if (status === "PASS") return "ok";
  if (status === "REJECTED") return "bad";
  if (status === "MANUAL_REVIEW") return "warn";
  return "info";
}

function describeFact(f: TraceFact): Step {
  const v = asObj(f.value);
  const k = f.key;
  const s = (v.status as string) ?? undefined;
  const str = (x: unknown) => (x == null || x === "" ? "—" : String(x));

  if (k === "submission") {
    return {
      phase: "Intake",
      title: "Claim received",
      detail: `${str(v.claim_category)} · ₹${str(v.claimed_amount)} claimed · treatment ${str(v.treatment_date)}`,
      tone: "info",
      issues: [],
    };
  }
  if (k === "member") {
    return {
      phase: "Identity",
      title: v.found ? "Member matched on roster" : "No member on record — fresh claimant",
      detail: v.found
        ? `Resolved member ${str(v.member_id)}.`
        : `${str(v.member_id)} is not on the roster, so identity & waiting-period checks are skipped.`,
      tone: v.found ? "ok" : "info",
      issues: [],
    };
  }
  if (k === "verdict.intake") {
    return {
      phase: "Intake",
      title: "Intake validation",
      detail: s === "PASS" ? "Claim is well-formed and above the minimum amount." : str(v.message),
      tone: statusTone(s, f.degraded),
      issues: s === "REJECTED" && v.message ? [String(v.message)] : [],
    };
  }

  if (k.startsWith("extraction.")) {
    if (v.system_error) {
      return { phase: "Extraction", title: "Document service failed", detail: str(v.message), tone: "bad", issues: [] };
    }
    const c = asObj(v.content);
    const bits = [
      v.patient_name ? `patient ${str(v.patient_name)}` : null,
      c.date ? `dated ${str(c.date)}` : null,
      c.total != null ? `total ₹${str(c.total)}` : null,
    ].filter(Boolean);
    const readable = v.readable !== false;
    return {
      phase: "Extraction",
      title: `Read ${str(v.doc_type) === "—" ? "document" : str(v.doc_type)}`,
      detail: readable
        ? bits.length
          ? bits.join(" · ")
          : "Extracted, no key fields."
        : "Could not be read — flagged to the document gate.",
      tone: readable ? "ok" : "bad",
      issues: [],
    };
  }

  if (k === "gate") {
    const issues = (v.issues as string[]) ?? [];
    return {
      phase: "Document gate",
      title: v.blocked ? `Documents blocked — ${issues.length} issue${issues.length === 1 ? "" : "s"}` : "Documents cleared",
      detail: v.blocked
        ? "All document problems are collected here so they can be fixed in one round-trip."
        : `Required types present: ${((v.present_types as string[]) ?? []).join(", ") || "—"}.`,
      tone: v.blocked ? "bad" : "ok",
      issues,
    };
  }

  if (k === "semantic") {
    return {
      phase: "Coverage",
      title: "Mapped charges to policy",
      detail: v.category_covered ? `${str(v.category)} is a covered OPD category.` : `${str(v.category)} is not a covered category.`,
      tone: v.category_covered ? "ok" : "warn",
      issues: [],
    };
  }
  if (k === "coverage" || k === "coverage.revised") {
    const excluded = Number(v.excluded_count ?? 0);
    const whole = Boolean(v.whole_claim_excluded);
    return {
      phase: "Coverage",
      title: whole ? "Whole claim excluded" : excluded ? `${excluded} line item${excluded === 1 ? "" : "s"} excluded` : "All charges covered",
      detail: str(v.message) === "—" ? "Every charge maps to a covered benefit." : str(v.message),
      tone: whole ? "bad" : excluded ? "warn" : "ok",
      issues: whole || excluded ? (v.message ? [String(v.message)] : []) : [],
    };
  }

  const RULES: Record<string, string> = {
    "verdict.waiting": "Waiting period",
    "verdict.preauth": "Pre-authorisation",
    "verdict.perclaim": "Per-claim limit",
  };
  if (k in RULES) {
    return {
      phase: "Rules & limits",
      title: RULES[k],
      detail: s === "PASS" ? `${RULES[k]} check passed${v.binding_ceiling ? ` (ceiling ₹${str(v.binding_ceiling)})` : ""}.` : str(v.message),
      tone: statusTone(s, f.degraded),
      issues: s === "REJECTED" || s === "MANUAL_REVIEW" ? (v.message ? [String(v.message)] : []) : [],
    };
  }

  const FRAUD: Record<string, string> = {
    "verdict.fraud": "Velocity / fraud screen",
    "verdict.docfraud": "Document-fraud screen",
    "verdict.prescription": "Prescription corroboration",
  };
  if (k in FRAUD) {
    return {
      phase: "Fraud & integrity",
      title: FRAUD[k],
      detail: s === "PASS" ? `${FRAUD[k]} clear.` : str(v.message),
      tone: statusTone(s, f.degraded),
      issues: s === "REJECTED" || s === "MANUAL_REVIEW" ? (v.message ? [String(v.message)] : []) : [],
    };
  }

  if (k === "verdict.consistency") {
    const disc = (v.discrepancies as string[]) ?? (v.message ? [String(v.message)] : []);
    return {
      phase: "Consistency",
      title: s === "PASS" ? "Form ↔ documents consistent" : `Three-way match — ${disc.length} mismatch${disc.length === 1 ? "" : "es"}`,
      detail: s === "PASS" ? "Claimed amount and date line up with the documents." : "The claim form disagrees with the evidence — routed to a human.",
      tone: statusTone(s, f.degraded),
      issues: s === "PASS" ? [] : disc,
    };
  }

  if (k === "financial_facts") {
    return {
      phase: "Financial",
      title: "Reconciled bill totals",
      detail: `Line items ₹${str(v.line_sum)} vs bill total ₹${str(v.bill_total)}${v.divergence ? " — divergent" : " — agree"}.`,
      tone: v.divergence ? "warn" : "ok",
      issues: [],
    };
  }
  if (k === "financial_breakdown") {
    return {
      phase: "Financial",
      title: "Computed payout",
      detail: `Approved ₹${str(v.approved_amount)} from gross ₹${str(v.gross)}${v.note ? ` · ${str(v.note)}` : ""}.`,
      tone: "info",
      issues: [],
    };
  }

  if (k === "preliminary_decision") {
    return { phase: "Reasoning", title: "Preliminary read", detail: str(v.label) === "—" ? str(v.status) : str(v.label), tone: "info", issues: [] };
  }
  if (k === "policy_reasoning") {
    return { phase: "Reasoning", title: `Policy reasoning — ${str(v.verdict)}`, detail: str(v.rationale), tone: v.verdict === "CONFIRM" ? "ok" : "warn", issues: [] };
  }
  if (k.startsWith("flag.")) {
    return { phase: "Reasoning", title: "Flagged for review", detail: str(v.message), tone: "warn", issues: v.message ? [String(v.message)] : [] };
  }

  if (k.startsWith("skipped.")) {
    return {
      phase: "Skipped",
      title: `Skipped ${k.replace("skipped.", "")}`,
      detail:
        f.reason === "GATE_BLOCKED"
          ? "Not run — the document gate already blocked the claim."
          : f.reason === "PROVABLY_PASS"
            ? "Not needed — provably passes."
            : str(f.reason),
      tone: "muted",
      issues: [],
    };
  }

  return {
    phase: "Other",
    title: f.key,
    detail: typeof f.value === "string" ? f.value : JSON.stringify(f.value).slice(0, 120),
    tone: f.degraded ? "bad" : "info",
    issues: [],
  };
}

export function EvalView({ engine }: EngineProps) {
  const { state, patch, selectedEmployee, selectEmployee, uploadDoc, removeDoc, runEval } = engine;
  const emp = selectedEmployee();
  const [preview, setPreview] = useState<EmployeeDocument | null>(null);

  const dec = state.evalDecision;
  const facts = [...state.evalFacts].sort((a, b) => a.seq - b.seq);
  let prevT = 0;
  const steps = facts.map((f) => {
    const tMs = f.tMs ?? prevT;
    const delta = Math.max(0, tMs - prevT);
    prevT = tMs;
    return { f, step: describeFact(f), tMs, delta };
  });
  const maxDelta = Math.max(1, ...steps.map((x) => x.delta));
  const allIssues = Array.from(new Set(steps.flatMap(({ step }) => step.issues).filter((x) => x && x.trim())));
  const passed = steps.filter(({ step }) => step.tone === "ok").length;

  const pickEmployee = (id: string) => {
    const next = state.employees.find((e) => e.id === id);
    if (next) selectEmployee(next);
  };

  return (
    <div className="rise">
      {/* console-style header — visually distinct from the demo view */}
      <div className="tester-head">
        <div className="row between center wrap" style={{ gap: 12 }}>
          <div className="row center" style={{ gap: 10 }}>
            <span className="mono" style={{ fontSize: 12, color: "var(--on-ink-soft)" }}>$</span>
            <span style={{ fontWeight: 700, fontSize: 17, color: "var(--on-ink)" }}>trace · lifecycle inspector</span>
          </div>
          <span className="mono" style={{ fontSize: 11, color: "var(--on-ink-soft)" }}>
            developer-in-the-loop · validates &amp; times every step
          </span>
        </div>
        <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--on-ink-soft)", marginTop: 6, maxWidth: 680 }}>
          The same claim as the demo — same roster, documents and fields — but instead of just the verdict you
          watch the engine think: every fact it posts, whether each check passed, and how long it took.
        </div>
      </div>

      {/* compact run-config bar (no big sidebar) */}
      <div className="config-bar">
        <div className="row between center wrap" style={{ gap: 12, marginBottom: 14 }}>
          <span className="mono section-label" style={{ margin: 0 }}>// configure run</span>
          {emp?.expected_status && (
            <span className="pill status-pill" style={{ background: STATUS_COLORS[(emp.expected_status as Status) || "MANUAL_REVIEW"], fontSize: 11 }}>
              expects {emp.expected_status.replace("_", " ")}
            </span>
          )}
        </div>

        {state.employeesLoading ? (
          <div className="row center" style={{ gap: 10 }}>
            <span className="spinner" />
            <span style={{ fontSize: 13, color: "var(--muted)" }}>Loading roster…</span>
          </div>
        ) : state.employeesError ? (
          <div style={{ fontSize: 13, color: "var(--st-rejected)" }}>{state.employeesError}</div>
        ) : (
          <>
            <div className="config-grid">
              <div style={{ gridColumn: "span 2" }}>
                <label className="field-label">Employee (case)</label>
                <Select value={state.selectedEmployeeId || ""} onChange={pickEmployee}>
                  {state.employees.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.case_id} · {p.name} — {p.case_name}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="field-label">Date of treatment</label>
                <input className="input" type="date" value={state.date} onChange={(e) => patch({ date: e.target.value })} />
              </div>
              <div>
                <label className="field-label">Treatment type</label>
                <Select value={state.treatment} onChange={(v) => patch({ treatment: v })}>
                  {CATEGORY_OPTIONS.map((c) => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="field-label">Claimed amount (₹)</label>
                <input
                  className="input"
                  type="text"
                  inputMode="numeric"
                  value={state.amount || ""}
                  placeholder="0"
                  onChange={(e) => {
                    const digits = e.target.value.replace(/[^0-9]/g, "");
                    patch({ amount: digits ? Number(digits) : 0 });
                  }}
                />
              </div>
              <div>
                <label className="field-label">Hospital / provider</label>
                <input className="input" type="text" value={state.hospital} placeholder="e.g. Apollo Hospitals" onChange={(e) => patch({ hospital: e.target.value })} />
              </div>
            </div>

            {/* compact document strip */}
            <div className="row center wrap" style={{ gap: 8, marginTop: 14 }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
                docs{state.docsLoading ? " · loading…" : ` (${state.employeeDocs.length})`}
              </span>
              {state.employeeDocs.map((d) => (
                <button
                  key={d.id}
                  className="pill"
                  onClick={() => setPreview(d)}
                  title="Click to preview"
                  style={{
                    cursor: "pointer",
                    gap: 6,
                    padding: "6px 10px",
                    fontSize: 12,
                    fontWeight: 500,
                    border: `1px solid ${d.is_user_uploaded ? "var(--primary)" : "var(--hairline)"}`,
                    background: "var(--surface-card)",
                    color: d.is_user_uploaded ? "var(--primary)" : "var(--ink)",
                  }}
                >
                  {iconFor(d.file_name)} {d.file_name}
                  <span
                    onClick={(e) => {
                      e.stopPropagation();
                      removeDoc(d);
                    }}
                    style={{ marginLeft: 2, color: "var(--muted)", fontWeight: 700 }}
                    title="Remove from this run"
                  >
                    ×
                  </span>
                </button>
              ))}
              <label className="attach" style={{ padding: "6px 10px", fontSize: 12, ...(state.uploadingDoc ? { opacity: 0.6 } : {}) }}>
                {state.uploadingDoc ? "uploading…" : "+ attach"}
                <input
                  type="file"
                  multiple
                  disabled={state.uploadingDoc}
                  onChange={(e) => {
                    uploadDoc(e.target.files);
                    e.target.value = "";
                  }}
                  style={{ display: "none" }}
                />
              </label>
            </div>

            {state.evalError && (
              <div className="row" style={{ gap: 9, alignItems: "flex-start", marginTop: 14, padding: "11px 13px", background: "var(--st-rejected-soft)", border: "1px solid #f3cfc1", borderRadius: 10 }}>
                <span style={{ fontSize: 14 }}>⚠️</span>
                <span style={{ fontWeight: 500, fontSize: 13, lineHeight: 1.45, color: "var(--st-rejected)" }}>{state.evalError}</span>
              </div>
            )}

            <button className="btn btn-primary btn-lg" style={{ marginTop: 16 }} disabled={state.evalBusy || !emp} onClick={runEval}>
              {state.evalBusy ? "Tracing every step…" : "▶ Run with full trace"}
            </button>
          </>
        )}
      </div>

      {/* lifecycle output */}
      {state.evalBusy && (
        <div className="card rise" style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 14 }}>
          <span className="spinner" />
          <span style={{ fontSize: 14, color: "var(--body)" }}>Running the agent graph and recording every step…</span>
        </div>
      )}

      {dec && state.evalRan && !state.evalBusy && (
        <div className="col" style={{ gap: 16, marginTop: 16 }}>
          {/* decision + timing banner */}
          <div className="card" style={{ padding: 20 }}>
            <div className="row between center wrap" style={{ gap: 12 }}>
              <div className="row center" style={{ gap: 12 }}>
                <span className="pill status-pill" style={{ background: STATUS_COLORS[dec.status as Status], fontSize: 13 }}>
                  {statusLabel(dec.status as Status)}
                </span>
                <span style={{ fontWeight: 600, fontSize: 15, color: "var(--ink)" }}>
                  {dec.status === "REJECTED" || dec.status === "BLOCKED" ? "Nothing payable" : `Payout ${fmt(dec.approved)}`}
                </span>
              </div>
              <div className="row center" style={{ gap: 18 }}>
                <Metric label="run time" value={`${state.evalElapsed.toFixed(2)}s`} />
                <Metric label="steps" value={String(facts.length)} />
                <Metric label="passed" value={`${passed}/${facts.length}`} />
                <Metric label="confidence" value={dec.conf != null ? dec.conf.toFixed(2) : "—"} />
              </div>
            </div>
            {dec.message && <div style={{ marginTop: 12, fontSize: 13, lineHeight: 1.5, color: "var(--body)" }}>{dec.message}</div>}
          </div>

          {/* every issue found */}
          {allIssues.length > 0 && (
            <div className="card" style={{ padding: 20, borderColor: "var(--st-rejected)" }}>
              <div className="section-label" style={{ color: "var(--st-rejected)", marginBottom: 12 }}>
                {allIssues.length} issue{allIssues.length === 1 ? "" : "s"} found — all of them
              </div>
              <div className="col" style={{ gap: 10 }}>
                {allIssues.map((iss, i) => (
                  <div key={i} className="row" style={{ gap: 10, alignItems: "flex-start" }}>
                    <span style={{ color: "var(--st-rejected)", fontWeight: 700, fontSize: 13, lineHeight: 1.5 }}>{i + 1}.</span>
                    <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--body)" }}>{iss}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* lifecycle timeline */}
          <div className="card" style={{ padding: 20 }}>
            <div className="row between center wrap" style={{ gap: 8, marginBottom: 14 }}>
              <div className="section-label" style={{ margin: 0 }}>Lifecycle · {facts.length} steps</div>
              <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
                bar = time spent · longest {Math.round(maxDelta)}ms
              </span>
            </div>
            <div className="tl">
              {steps.map(({ f, step, tMs, delta }, i) => (
                <TimelineRow key={f.seq} fact={f} step={step} tMs={tMs} delta={delta} maxDelta={maxDelta} index={i} />
              ))}
              {/* final decision node */}
              <div className="tl-row" style={{ animationDelay: `${steps.length * 28}ms` }}>
                <span className="tl-node" style={{ background: STATUS_COLORS[dec.status as Status], fontSize: 14 }}>✓</span>
                <div className="row center wrap" style={{ gap: 8 }}>
                  <span style={{ fontWeight: 700, fontSize: 15, color: "var(--ink)" }}>Decision · {statusLabel(dec.status as Status)}</span>
                  <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>end-to-end {state.evalElapsed.toFixed(2)}s</span>
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--body)", marginTop: 3 }}>
                  {dec.reasons.length
                    ? `Ranked reason: ${dec.reasons.join(", ")}.`
                    : dec.status === "APPROVED"
                      ? `All checks passed — ${fmt(dec.approved)} approved.`
                      : dec.message || "Aggregated from the facts above."}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {preview && <DocPreview doc={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

// ── presentational helpers ────────────────────────────────────────────────────

function TimelineRow({
  fact,
  step,
  tMs,
  delta,
  maxDelta,
  index,
}: {
  fact: TraceFact;
  step: Step;
  tMs: number;
  delta: number;
  maxDelta: number;
  index: number;
}) {
  const color = TONE_COLOR[step.tone];
  const pct = Math.max(delta > 0 ? 5 : 0, Math.round((delta / maxDelta) * 100));
  return (
    <div className="tl-row" style={{ animationDelay: `${index * 28}ms` }}>
      <span className="tl-node mono" style={{ background: color, fontSize: 11, fontWeight: 700 }}>
        {PHASE_CODE[step.phase] ?? "•"}
      </span>
      <div className="row between" style={{ gap: 10, alignItems: "flex-start" }}>
        <div className="col" style={{ gap: 3, minWidth: 0, flex: 1 }}>
          <div className="row center wrap" style={{ gap: 8 }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted-soft)" }}>#{fact.seq}</span>
            <span style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)" }}>{step.title}</span>
            <span className="pill" style={{ fontSize: 10, fontWeight: 700, background: "transparent", color, border: `1px solid ${color}` }}>
              {TONE_VERDICT[step.tone]}
            </span>
            {fact.conf != null && <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>conf {fact.conf.toFixed(2)}</span>}
            {fact.degraded && <span className="pill" style={{ background: "var(--st-rejected)", color: "#fff", fontSize: 10 }}>degraded</span>}
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--body)" }}>{step.detail}</div>
          {step.issues.length > 0 && (
            <div className="col" style={{ gap: 6, marginTop: 6 }}>
              {step.issues.map((iss, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: 12,
                    lineHeight: 1.45,
                    color,
                    background: step.tone === "bad" ? "var(--st-rejected-soft)" : "var(--st-partial-soft)",
                    borderRadius: 8,
                    padding: "7px 10px",
                  }}
                >
                  ⚠ {iss}
                </div>
              ))}
            </div>
          )}
          {/* duration bar */}
          <div className="tl-bar-track">
            <div className="tl-bar-fill" style={{ width: `${pct}%`, background: color, opacity: delta > 0 ? 0.85 : 0 }} />
          </div>
          {fact.derivedFrom && fact.derivedFrom.length > 0 && (
            <div className="mono" style={{ fontSize: 10, color: "var(--muted-soft)", marginTop: 4 }}>← {fact.derivedFrom.join(", ")}</div>
          )}
        </div>
        <div className="col" style={{ alignItems: "flex-end", flex: "0 0 auto", gap: 1 }}>
          <span className="pill" style={{ fontSize: 9, letterSpacing: ".04em", textTransform: "uppercase", background: "var(--canvas-soft)", color: "var(--muted)", border: "1px solid var(--hairline)" }}>
            {step.phase}
          </span>
          <span className="mono" style={{ fontSize: 11, fontWeight: 600, color: delta > 100 ? "var(--st-partial)" : "var(--muted)", marginTop: 3 }}>
            +{delta < 1 ? "<1" : Math.round(delta)}ms
          </span>
          <span className="mono" style={{ fontSize: 9, color: "var(--muted-soft)" }}>@{Math.round(tMs)}ms</span>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="col" style={{ alignItems: "center", gap: 2 }}>
      <span className="mono" style={{ fontSize: 16, fontWeight: 600, color: "var(--ink)" }}>{value}</span>
      <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)" }}>{label}</span>
    </div>
  );
}
