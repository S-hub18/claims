"use client";

import type { EngineProps } from "./ui";
import { StatusPill } from "./ui";
import { fmt } from "@/lib/format";

export function ResultPanel({ engine }: EngineProps) {
  const { state, rerun, resubmit, toggleTrace } = engine;
  const dec = state.decision;
  if (!dec) return null;

  const isBlocked = dec.kind === "blocked";
  const isFinancial = dec.waterfall.length > 0 && !isBlocked;
  const hasReasons = dec.reasons.length > 0;
  const hasNotes = dec.notes.length > 0;

  return (
    <div className="row wrap pop" style={{ marginTop: 22, gap: 18, alignItems: "flex-start" }}>
      <div className="card" style={{ flex: 1, minWidth: 340, padding: 28 }}>
        <div className="row center wrap" style={{ gap: 12 }}>
          <StatusPill status={dec.status} />
          <span style={{ fontWeight: 500, fontSize: 13, color: "var(--body)" }}>
            {dec.conf != null ? `confidence ${dec.conf.toFixed(2)} · ${dec.confBand}` : "document gate"}
          </span>
          <span className="mono" style={{ fontSize: 12, color: "var(--muted-soft)", marginLeft: "auto" }}>
            claim {dec.claimId} · {dec.category}
          </span>
        </div>

        <div style={{ fontSize: 16, lineHeight: 1.55, color: "var(--ink)", margin: "16px 0 4px", maxWidth: 560 }}>
          {dec.message}
        </div>

        {/* BLOCKED — collect-all */}
        {isBlocked && (
          <>
            <div className="section-label" style={{ margin: "18px 0 10px" }}>
              Fix these {dec.issues.length} things, then resubmit once
            </div>
            <div className="col" style={{ gap: 10 }}>
              {dec.issues.map((i) => (
                <div
                  key={i.n}
                  className="row"
                  style={{ gap: 11, padding: 13, background: "var(--st-rejected-soft)", border: "1px solid #f3cfc1", borderRadius: 12 }}
                >
                  <span
                    style={{
                      flex: "none",
                      width: 22,
                      height: 22,
                      borderRadius: "50%",
                      background: "var(--st-rejected)",
                      color: "#fff",
                      fontWeight: 700,
                      fontSize: 12,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    {i.n}
                  </span>
                  <span className="col" style={{ gap: 2 }}>
                    <span style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)" }}>{i.title}</span>
                    <span style={{ fontSize: 13, lineHeight: 1.45, color: "var(--body)" }}>{i.detail}</span>
                  </span>
                </div>
              ))}
            </div>
            <div className="row" style={{ gap: 10, marginTop: 18 }}>
              <button
                className="btn btn-primary"
                onClick={() => {
                  // Dismiss the blocked result and take the user back to the
                  // documents/setup so they can attach the corrected file and
                  // run the adjudication again.
                  resubmit();
                  if (typeof document !== "undefined") {
                    document
                      .getElementById("claim-setup")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }
                }}
              >
                Fix &amp; resubmit
              </button>
            </div>
          </>
        )}

        {/* FINANCIAL — lines + waterfall */}
        {isFinancial && (
          <>
            <div className="col" style={{ gap: 8, margin: "18px 0 6px" }}>
              {dec.lines.map((l, i) => (
                <div
                  key={i}
                  className="row between center"
                  style={{ gap: 10, padding: "11px 13px", background: "var(--canvas-soft)", borderRadius: 9 }}
                >
                  <span className="col" style={{ gap: 2 }}>
                    <span style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)" }}>{l.label}</span>
                    {l.ref ? (
                      <span className="mono" style={{ fontSize: 11, color: "var(--muted-soft)" }}>
                        {l.ref}
                      </span>
                    ) : null}
                  </span>
                  <span className="row center" style={{ gap: 9 }}>
                    <span className="tag" style={{ background: l.tag === "excluded" ? "var(--st-rejected)" : "var(--st-approved)" }}>
                      {l.tag}
                    </span>
                    <span style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)" }} className="mono">
                      {l.amount}
                    </span>
                  </span>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10 }}>
              {dec.waterfall.map((w, i) => (
                <div key={i} className={`waterfall-row${w.final ? " final" : ""}`}>
                  <span
                    style={{
                      fontWeight: w.final ? 600 : 500,
                      fontSize: w.final ? 16 : 14,
                      color: w.muted ? "var(--muted-soft)" : w.final ? "var(--ink)" : "var(--body)",
                    }}
                  >
                    {w.label}
                  </span>
                  <span
                    className="mono"
                    style={{
                      fontWeight: w.final ? 600 : 500,
                      fontSize: w.final ? 28 : 15,
                      letterSpacing: w.final ? "-0.02em" : 0,
                      color: w.final ? "var(--primary)" : w.neg ? "var(--st-rejected)" : w.muted ? "var(--muted-soft)" : "var(--ink)",
                    }}
                  >
                    {w.val}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {/* REASONS */}
        {hasReasons && (
          <>
            <div className="section-label" style={{ margin: "18px 0 10px" }}>
              Why
            </div>
            <div className="col" style={{ gap: 8 }}>
              {dec.reasons.map((r, i) => (
                <div
                  key={i}
                  className="row"
                  style={{ gap: 9, alignItems: "flex-start", padding: "11px 13px", background: "var(--canvas-soft)", borderRadius: 9 }}
                >
                  <span style={{ color: "var(--primary)", fontWeight: 700, fontSize: 14 }}>›</span>
                  <span style={{ fontWeight: 500, fontSize: 14, lineHeight: 1.45, color: "var(--ink)" }}>{r}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {/* NOTES */}
        {hasNotes && (
          <div className="col" style={{ gap: 8, marginTop: 16 }}>
            {dec.notes.map((note, i) => (
              <div
                key={i}
                className="row"
                style={{ gap: 9, alignItems: "flex-start", padding: "11px 13px", background: "var(--st-partial-soft)", border: "1px solid #ecd9b0", borderRadius: 10 }}
              >
                <span style={{ fontSize: 14 }}>⚠️</span>
                <span style={{ fontWeight: 500, fontSize: 13, lineHeight: 1.45, color: "var(--st-partial)" }}>{note}</span>
              </div>
            ))}
          </div>
        )}

        <div
          className="row wrap"
          style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--hairline-soft)", gap: 14 }}
        >
          <button className="btn btn-secondary" onClick={rerun}>
            Run again
          </button>
          <button className="btn btn-text" onClick={toggleTrace}>
            {state.traceOpen ? "Hide trace" : "View full trace"}
          </button>
        </div>

        {state.traceOpen && (
          <div className="trace">
            <div className="section-label" style={{ color: "var(--primary)", marginBottom: 10 }}>
              Trace · {state.facts.length} facts · sorted by seq
            </div>
            {state.facts.map((f) => (
              <div key={f.seq} className="trace-row">
                <span className="mono" style={{ fontSize: 10, color: "var(--on-ink-soft)" }}>
                  {f.seq}
                </span>
                <span className="col">
                  <span className="mono" style={{ fontSize: 11, color: "var(--on-ink)" }}>{f.key}</span>
                  <span style={{ fontSize: 10, color: "var(--on-ink-soft)" }}>
                    {f.author} · {f.reason || "derived"}
                  </span>
                </span>
                <span className="mono" style={{ fontSize: 10, color: "var(--primary)", whiteSpace: "nowrap" }}>
                  {f.conf != null ? f.conf.toFixed(2) : "—"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* side summary */}
      <div className="payout-card">
        <div className="section-label" style={{ color: "var(--on-ink-soft)" }}>
          {dec.status === "REJECTED" || dec.status === "BLOCKED" ? "Payable" : "Approved payout"}
        </div>
        <div className="payout-amount">{fmt(dec.approved)}</div>
        <div style={{ fontWeight: 500, fontSize: 13, color: "var(--on-ink-soft)" }}>
          of {fmt(dec.claimed)} claimed
        </div>
        <div style={{ height: 1, background: "var(--ink-surface-2)", margin: "20px 0" }} />
        <div className="col" style={{ gap: 12 }}>
          <SummaryRow label="Confidence" value={dec.conf != null ? dec.conf.toFixed(2) : "—"} />
          <SummaryRow label="Decided in" value={`${state.elapsed.toFixed(1)}s`} />
          <SummaryRow label="Policy" value={state.policyVersion} />
          <SummaryRow label="Agents fired" value={String(state.agentsFired)} />
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="row between">
      <span style={{ fontWeight: 500, fontSize: 13, color: "var(--on-ink-soft)" }}>{label}</span>
      <span className="mono" style={{ fontWeight: 600, fontSize: 13, color: "var(--on-ink)" }}>
        {value}
      </span>
    </div>
  );
}
