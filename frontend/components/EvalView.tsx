"use client";

import type { EngineProps } from "./ui";
import { Select, STATUS_COLORS, statusLabel } from "./ui";
import { fmt } from "@/lib/format";
import { TEST_CASES } from "@/lib/testcases";
import type { Status } from "@/lib/types";

export function EvalView({ engine }: EngineProps) {
  const { state, patch, runAllEvals, addCustomEval, onEvalFiles } = engine;
  const allCases = [...TEST_CASES, ...state.customEvals];
  const results = state.evalResults;

  const doneCases = allCases.filter((c) => results[c.id]?.done);
  const passed = doneCases.filter((c) => results[c.id].pass).length;
  const confs = doneCases.map((c) => results[c.id].conf).filter((x): x is number => x != null);
  const avgConf = confs.length ? (confs.reduce((a, b) => a + b, 0) / confs.length).toFixed(2) : "—";
  const totalTime = doneCases.length
    ? (Math.max(...doneCases.map((c) => results[c.id].ms || 0)) / 1000).toFixed(2) + "s"
    : "—";
  const allPassed = doneCases.length === allCases.length && passed === allCases.length;

  return (
    <div className="rise">
      <div className="row between wrap" style={{ alignItems: "flex-end", gap: 18, margin: "28px 0 20px" }}>
        <div>
          <div className="view-title">Evaluation suite</div>
          <div className="view-sub">
            Run all {TEST_CASES.length} graded test cases live. Each asserts the decision &amp; payout
            against its expected outcome and reports the time taken.
          </div>
        </div>
        <button className="btn btn-primary" disabled={state.evalRunning} onClick={runAllEvals}>
          {state.evalRunning ? "Running…" : state.evalStarted ? "Run again" : "Run all evals →"}
        </button>
      </div>

      {/* aggregate */}
      <div className="row wrap" style={{ gap: 14, marginBottom: 20 }}>
        <div className="stat-card">
          <div className="stat-num" style={{ color: allPassed ? "var(--st-approved)" : "var(--primary)" }}>
            {state.evalStarted ? `${passed}/${allCases.length}` : `—/${allCases.length}`}
          </div>
          <div className="section-label" style={{ marginTop: 2 }}>passed</div>
        </div>
        <div className="stat-card">
          <div className="stat-num" style={{ color: "var(--ink)" }}>{totalTime}</div>
          <div className="section-label" style={{ marginTop: 2 }}>total wall time</div>
        </div>
        <div className="stat-card">
          <div className="stat-num" style={{ color: "var(--ink)" }}>{avgConf}</div>
          <div className="section-label" style={{ marginTop: 2 }}>avg confidence</div>
        </div>
        <div className="stat-card">
          <div className="stat-num" style={{ color: "var(--ink)" }}>
            {doneCases.length}/{allCases.length}
          </div>
          <div className="section-label" style={{ marginTop: 2 }}>cases run</div>
        </div>
      </div>

      <div className="eval-grid">
        {allCases.map((c) => {
          const r = results[c.id];
          const done = r?.done;
          const running = r?.running && !done;
          const stateLabel = done ? "done" : running ? "running…" : state.evalStarted ? "queued" : "ready";
          return (
            <div
              key={c.id}
              className={`card${done ? " pop" : ""}`}
              style={{ padding: 16, borderColor: running ? "var(--primary)" : "var(--hairline)" }}
            >
              <div className="row between center" style={{ gap: 8 }}>
                <span className="mono" style={{ fontWeight: 600, fontSize: 13, color: "var(--muted)" }}>{c.id}</span>
                <span
                  className="pill"
                  style={{
                    fontSize: 10,
                    letterSpacing: ".04em",
                    textTransform: "uppercase",
                    background: done ? "var(--st-approved-soft)" : running ? "var(--primary-tint)" : "var(--canvas-soft)",
                    color: done ? "var(--st-approved)" : running ? "var(--primary)" : "var(--muted)",
                  }}
                >
                  {stateLabel}
                </span>
              </div>
              <div style={{ fontWeight: 600, fontSize: 15, color: "var(--ink)", margin: "8px 0 4px", lineHeight: 1.3 }}>
                {c.title}
              </div>
              <div className="row center wrap" style={{ gap: 7 }}>
                <span className="pill" style={{ background: "var(--primary-tint)", color: "var(--primary)" }}>{c.cat}</span>
                <span style={{ fontWeight: 500, fontSize: 11, color: "var(--muted-soft)" }}>expects {c.expected}</span>
              </div>

              {done && (
                <div
                  className="col"
                  style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--hairline-soft)", gap: 7 }}
                >
                  <Row label="result">
                    <span className="row center" style={{ gap: 7 }}>
                      <span className="tag" style={{ background: STATUS_COLORS[r.actual as Status] }}>
                        {statusLabel(r.actual as Status)}
                      </span>
                      <span style={{ fontWeight: 700, fontSize: 11, color: r.pass ? "var(--st-approved)" : "var(--st-rejected)" }}>
                        {r.pass ? "✓ pass" : "✕ fail"}
                      </span>
                    </span>
                  </Row>
                  <Row label="payout">
                    <span className="mono" style={{ fontWeight: 600, fontSize: 12, color: "var(--ink)" }}>{fmt(r.approved)}</span>
                  </Row>
                  <Row label="confidence · time">
                    <span className="mono" style={{ fontWeight: 600, fontSize: 12, color: "var(--ink)" }}>
                      {(r.conf != null ? r.conf.toFixed(2) : "—") + " · " + ((r.ms || 0) / 1000).toFixed(2) + "s"}
                    </span>
                  </Row>
                  {r.note && (
                    <div
                      style={{ fontWeight: 500, fontSize: 11, lineHeight: 1.45, color: "var(--st-partial)", background: "var(--st-partial-soft)", borderRadius: 8, padding: "8px 10px", marginTop: 2 }}
                    >
                      ⚠️ {r.note}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* upload your own */}
      <div className="card" style={{ marginTop: 24 }}>
        <div style={{ fontWeight: 600, fontSize: 18, color: "var(--ink)" }}>Run evals on your own documents</div>
        <div style={{ fontWeight: 400, fontSize: 14, lineHeight: 1.5, color: "var(--body)", margin: "5px 0 16px", maxWidth: 620 }}>
          Upload one of the 5 document types, pick the outcome you expect, and add it to the suite —
          it runs alongside the built-in cases.
        </div>
        <div className="row wrap" style={{ gap: 14, alignItems: "flex-end" }}>
          <div style={{ flex: 2, minWidth: 200 }}>
            <label className="field-label" style={{ textTransform: "none", letterSpacing: 0, fontSize: 12, color: "var(--body)" }}>
              Case name
            </label>
            <input
              className="input"
              type="text"
              value={state.newEvalName}
              placeholder="e.g. My blurry pharmacy bill"
              onChange={(e) => patch({ newEvalName: e.target.value })}
            />
          </div>
          <div style={{ flex: 1, minWidth: 150 }}>
            <label className="field-label" style={{ textTransform: "none", letterSpacing: 0, fontSize: 12, color: "var(--body)" }}>
              Document type
            </label>
            <Select value={state.newEvalDoc} onChange={(v) => patch({ newEvalDoc: v })}>
              {["Prescription", "Hospital bill", "Lab report", "Discharge summary", "Pharmacy invoice"].map((d) => (
                <option key={d}>{d}</option>
              ))}
            </Select>
          </div>
          <div style={{ flex: 1, minWidth: 150 }}>
            <label className="field-label" style={{ textTransform: "none", letterSpacing: 0, fontSize: 12, color: "var(--body)" }}>
              Expected
            </label>
            <Select value={state.newEvalExp} onChange={(v) => patch({ newEvalExp: v as Status })}>
              {(["APPROVED", "PARTIAL", "REJECTED", "MANUAL_REVIEW", "BLOCKED"] as Status[]).map((s) => (
                <option key={s}>{s}</option>
              ))}
            </Select>
          </div>
          <label className="attach">
            📎 upload
            <input
              type="file"
              multiple
              onChange={(e) => {
                onEvalFiles(e.target.files);
                e.target.value = "";
              }}
              style={{ display: "none" }}
            />
          </label>
          <button className="btn btn-primary" onClick={addCustomEval}>
            Add case
          </button>
        </div>
        {state.evalFiles.length > 0 && (
          <div className="row wrap" style={{ gap: 8, marginTop: 14 }}>
            {state.evalFiles.map((d, i) => (
              <span
                key={i}
                className="pill"
                style={{ gap: 7, padding: "7px 11px", border: "1px solid var(--hairline)", background: "var(--canvas-soft)", color: "var(--ink)", fontWeight: 600, fontSize: 12 }}
              >
                {d.icon} {d.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="row between center">
      <span style={{ fontWeight: 500, fontSize: 12, color: "var(--body)" }}>{label}</span>
      {children}
    </div>
  );
}
