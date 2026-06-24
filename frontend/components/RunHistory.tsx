"use client";

import type { EngineProps } from "./ui";
import { STATUS_COLORS, statusLabel } from "./ui";

export function RunHistory({ engine }: EngineProps) {
  const { history } = engine.state;

  return (
    <div className="card" style={{ marginTop: 26, padding: "22px 24px" }}>
      <div className="section-label" style={{ marginBottom: 14 }}>
        Run history
      </div>

      {history.length === 0 ? (
        <div style={{ fontWeight: 500, fontSize: 14, color: "var(--muted-soft)", padding: "8px 0" }}>
          No runs yet. Adjudicate a claim and it&apos;ll show up here.
        </div>
      ) : (
        <>
          <div
            className="hist-grid section-label"
            style={{ padding: "9px 0", borderBottom: "1px solid var(--hairline-soft)" }}
          >
            <span>Claim</span>
            <span>Member · type</span>
            <span>Status</span>
            <span>Approved</span>
            <span>Conf</span>
            <span>Time</span>
          </div>
          {history.map((h, i) => (
            <div
              key={`${h.claimId}-${i}`}
              className="hist-grid"
              style={{ padding: "12px 0", fontWeight: 500, fontSize: 13, color: "var(--ink)", borderBottom: "1px solid var(--hairline-soft)" }}
            >
              <span className="mono" style={{ fontSize: 13, color: "var(--muted)" }}>{h.claimId}</span>
              <span>
                {h.member} · {h.category}
              </span>
              <span>
                <span className="tag" style={{ background: STATUS_COLORS[h.status] }}>
                  {statusLabel(h.status)}
                </span>
              </span>
              <span style={{ fontWeight: 600 }} className="mono">
                {h.approved}
              </span>
              <span className="mono" style={{ color: "var(--body)" }}>{h.conf}</span>
              <span className="mono" style={{ color: "var(--body)" }}>{h.time}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
