"use client";

import type { EngineProps } from "./ui";
import { STATUS_COLORS, statusLabel } from "./ui";
import { computeCustomDecision } from "@/lib/decision";
import { fmt, titleCase } from "@/lib/format";

export function PolicyPanel({ engine }: EngineProps) {
  const { state, activePolicy, onPolicyFile } = engine;
  const P = activePolicy();

  const { dec } = computeCustomDecision(
    {
      custTreatment: state.custTreatment,
      custAmount: state.custAmount,
      custHospital: state.custHospital,
      confThreshold: state.confThreshold,
    },
    P
  );

  const limits = [
    { label: "per claim", value: fmt(P.coverage?.per_claim_limit) },
    { label: "annual OPD", value: fmt(P.coverage?.annual_opd_limit) },
    { label: "sum insured", value: fmt(P.coverage?.sum_insured_per_employee) },
    { label: "manual review ≥", value: fmt(P.fraud_thresholds?.auto_manual_review_above) },
  ];

  const cats = Object.keys(P.opd_categories || {}).map((k) => {
    const c = P.opd_categories[k];
    const chips: { text: string; tone: string }[] = [];
    chips.push({ text: `co-pay ${c.copay_percent || 0}%`, tone: "neutral" });
    if (c.network_discount_percent) chips.push({ text: `network −${c.network_discount_percent}%`, tone: "good" });
    if (c.requires_pre_auth) chips.push({ text: "pre-auth", tone: "warn" });
    const exCount = (c.excluded_procedures || c.excluded_items || []).length;
    if (exCount) chips.push({ text: `${exCount} excluded`, tone: "bad" });
    return { name: titleCase(k), subLimit: fmt(c.sub_limit), chips };
  });

  const chipColor: Record<string, { bg: string; fg: string }> = {
    neutral: { bg: "var(--ink-surface-2)", fg: "var(--on-ink-soft)" },
    good: { bg: "#1c2c25", fg: "#7fcaa8" },
    warn: { bg: "#33291f", fg: "#e0a86a" },
    bad: { bg: "#33211f", fg: "#e09a86" },
  };

  return (
    <div
      className="card-ink"
      style={{ flex: "none", width: 336, padding: 22, maxHeight: 820, overflow: "auto" }}
    >
      <div className="row between center" style={{ gap: 10, marginBottom: 12 }}>
        <span className="section-label" style={{ color: "var(--primary)" }}>
          Policy document
        </span>
        <label
          style={{
            fontWeight: 700,
            fontSize: 11,
            color: "var(--ink)",
            background: "var(--on-ink)",
            padding: "6px 12px",
            borderRadius: "var(--r-pill)",
            cursor: "pointer",
          }}
        >
          Upload .json
          <input
            type="file"
            accept=".json,application/json"
            onChange={(e) => {
              onPolicyFile(e.target.files?.[0] || null);
              e.target.value = "";
            }}
            style={{ display: "none" }}
          />
        </label>
      </div>

      <div style={{ fontWeight: 500, fontSize: 12, lineHeight: 1.5, color: "var(--on-ink-soft)", marginBottom: 14 }}>
        {state.policyUploaded
          ? "This claim is adjudicated against your uploaded policy."
          : "No policy uploaded — the system's default policy is used as a backup. Upload a policy_terms.json to adjudicate this claim against your own."}
      </div>

      {state.policyError && (
        <div
          style={{ fontWeight: 600, fontSize: 12, color: "#f0a58a", background: "#3a241f", borderRadius: 8, padding: "9px 11px", marginBottom: 14 }}
        >
          ⚠️ {state.policyError}
        </div>
      )}

      <div style={{ background: "var(--ink-surface-2)", borderRadius: 10, padding: "13px 14px", marginBottom: 12 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: "var(--on-ink)", lineHeight: 1.3 }}>
          {P.policy_name || "Untitled policy"}
        </div>
        <div className="mono" style={{ fontSize: 11, color: "var(--on-ink-soft)", marginTop: 3 }}>
          {P.insurer}
          {P.policy_id ? ` · ${P.policy_id}` : ""}
        </div>
        <div className="row wrap" style={{ gap: 7, marginTop: 11 }}>
          {limits.map((l) => (
            <span key={l.label} className="col" style={{ gap: 1, background: "#1d1c16", borderRadius: 8, padding: "7px 10px" }}>
              <span className="mono" style={{ fontWeight: 600, fontSize: 13, color: "var(--primary)" }}>{l.value}</span>
              <span style={{ fontWeight: 600, fontSize: 9, letterSpacing: ".04em", textTransform: "uppercase", color: "var(--on-ink-soft)" }}>
                {l.label}
              </span>
            </span>
          ))}
        </div>
      </div>

      <div className="section-label" style={{ color: "var(--on-ink-soft)", margin: "14px 0 9px" }}>
        Parsed OPD categories
      </div>
      <div className="col" style={{ gap: 8 }}>
        {cats.map((c) => (
          <div key={c.name} style={{ background: "var(--ink-surface-2)", borderRadius: 9, padding: "10px 12px" }}>
            <div className="row between center" style={{ gap: 8 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: "var(--on-ink)" }}>{c.name}</span>
              <span className="mono" style={{ fontWeight: 600, fontSize: 12, color: "var(--primary)" }}>{c.subLimit}</span>
            </div>
            <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
              {c.chips.map((chip, i) => (
                <span
                  key={i}
                  style={{ fontWeight: 600, fontSize: 10, borderRadius: "var(--r-pill)", padding: "3px 9px", background: chipColor[chip.tone].bg, color: chipColor[chip.tone].fg }}
                >
                  {chip.text}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--ink-surface-2)" }}>
        <div style={{ fontWeight: 600, fontSize: 12, color: "var(--on-ink)", marginBottom: 8 }}>
          predicted path for this claim
        </div>
        <span className="pill status-pill" style={{ background: STATUS_COLORS[dec.status] }}>
          {statusLabel(dec.status)}
        </span>
        <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--on-ink-soft)", marginTop: 10 }}>
          {dec.message}
        </div>
      </div>
    </div>
  );
}
