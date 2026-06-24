"use client";

import type { EngineProps } from "./ui";
import { Select } from "./ui";

const TOGGLEABLE = [
  { id: "ClinicalChain", label: "ClinicalChain" },
  { id: "DocumentFraud", label: "DocFraudAgent" },
  { id: "VelocityFraud", label: "VelocityFraud" },
  { id: "Exclusion", label: "ExclusionAgent" },
  { id: "PreAuth", label: "PreAuthAgent" },
  { id: "PatientResolver", label: "PatientResolver" },
];

export function DevConfig({ engine }: EngineProps) {
  const { state, patch } = engine;
  if (!state.dev) return null;

  const setScope = (scope: "covered" | "billed") => patch({ subLimitScope: scope });
  const toggleAgent = (id: string) =>
    patch((st) => {
      const d = { ...st.disabled };
      if (d[id]) delete d[id];
      else d[id] = true;
      return { disabled: d };
    });

  return (
    <div className="dev-config">
      <div
        className="row center"
        style={{ gap: 8, marginBottom: 16, fontSize: 11, letterSpacing: ".07em", textTransform: "uppercase", fontWeight: 600, color: "var(--primary)" }}
      >
        ⚙ Developer config
        <span style={{ letterSpacing: 0, textTransform: "none", fontWeight: 500, color: "var(--on-ink-soft)" }}>
          — changes re-run the decision
        </span>
      </div>

      <div className="row wrap" style={{ gap: 22 }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8 }}>sub_limit_scope</div>
          <div className="seg">
            <button className={state.subLimitScope === "covered" ? "on" : ""} onClick={() => setScope("covered")}>
              covered
            </button>
            <button className={state.subLimitScope === "billed" ? "on" : ""} onClick={() => setScope("billed")}>
              billed
            </button>
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="row between" style={{ fontWeight: 600, fontSize: 12, marginBottom: 8 }}>
            <span>confidence threshold</span>
            <span style={{ color: "var(--primary)" }} className="mono">
              {state.confThreshold.toFixed(2)}
            </span>
          </div>
          <input
            className="range"
            type="range"
            min={0.5}
            max={0.95}
            step={0.01}
            value={state.confThreshold}
            onChange={(e) => patch({ confThreshold: Number(e.target.value) })}
          />
          <div style={{ fontWeight: 500, fontSize: 11, color: "var(--on-ink-soft)", marginTop: 4 }}>
            Below this, extraction escalates to manual review.
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8 }}>policy version</div>
          <Select value={state.policyVersion} onChange={(v) => patch({ policyVersion: v })}>
            <option value="v9">v9 · 2026-06-21</option>
            <option value="v8">v8 · 2026-05-30</option>
            <option value="v7">v7 · 2026-04-12</option>
          </Select>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 9 }}>
          toggle agents{" "}
          <span style={{ fontWeight: 500, color: "var(--on-ink-soft)" }}>
            — disabling one posts a degraded fact &amp; lowers confidence
          </span>
        </div>
        <div className="row wrap" style={{ gap: 7 }}>
          {TOGGLEABLE.map((t) => (
            <button
              key={t.id}
              className={`agent-toggle${state.disabled[t.id] ? " off" : ""}`}
              onClick={() => toggleAgent(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
