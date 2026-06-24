"use client";

import type { EngineProps } from "./ui";
import { STATUS_COLORS, statusLabel } from "./ui";
import { computeCustomDecision } from "@/lib/decision";
import { titleCase } from "@/lib/format";

export function PolicyPanel({ engine }: EngineProps) {
  const { state, activePolicy, onPolicyFile, setPolicyValue } = engine;
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

  const topLimits = [
    { label: "per claim", path: "coverage.per_claim_limit", value: P.coverage?.per_claim_limit },
    { label: "annual OPD", path: "coverage.annual_opd_limit", value: P.coverage?.annual_opd_limit },
    { label: "sum insured", path: "coverage.sum_insured_per_employee", value: P.coverage?.sum_insured_per_employee },
    { label: "manual review ≥", path: "fraud_thresholds.auto_manual_review_above", value: P.fraud_thresholds?.auto_manual_review_above },
  ];

  return (
    <div className="card-ink" style={{ flex: "none", width: 336, padding: 22, maxHeight: 860, overflow: "auto" }}>
      <div className="row between center" style={{ gap: 10, marginBottom: 12 }}>
        <span className="section-label" style={{ color: "var(--primary)" }}>Policy document</span>
        <label
          style={{ fontWeight: 700, fontSize: 11, color: "var(--ink)", background: "var(--on-ink)", padding: "6px 12px", borderRadius: "var(--r-pill)", cursor: "pointer" }}
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

      <div style={{ fontWeight: 500, fontSize: 12, lineHeight: 1.5, color: "var(--on-ink-soft)", marginBottom: 16 }}>
        {state.policyUploaded
          ? "Every value below is editable — this claim is adjudicated against your edited policy."
          : "Every value below is editable. Change any field (or upload a policy_terms.json) and the claim runs against your version."}
      </div>

      {state.policyError && (
        <div style={{ fontWeight: 600, fontSize: 12, color: "#f0a58a", background: "#3a241f", borderRadius: 8, padding: "9px 11px", marginBottom: 14 }}>
          ⚠️ {state.policyError}
        </div>
      )}

      <div style={{ background: "var(--ink-surface-2)", borderRadius: 10, padding: "14px 15px", marginBottom: 12 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: "var(--on-ink)", lineHeight: 1.3 }}>
          {P.policy_name || "Untitled policy"}
        </div>
        <div className="mono" style={{ fontSize: 11, color: "var(--on-ink-soft)", marginTop: 3, marginBottom: 13 }}>
          {P.insurer}
          {P.policy_id ? ` · ${P.policy_id}` : ""}
        </div>
        <div className="policy-grid">
          {topLimits.map((l) => (
            <Field key={l.path} label={l.label} affix="₹" value={l.value} onChange={(v) => setPolicyValue(l.path, v)} />
          ))}
        </div>
      </div>

      <div className="section-label" style={{ color: "var(--on-ink-soft)", margin: "16px 0 9px" }}>
        OPD categories
      </div>
      <div className="col" style={{ gap: 8 }}>
        {Object.keys(P.opd_categories || {}).map((k) => {
          const c = P.opd_categories[k];
          const exCount = (c.excluded_procedures || c.excluded_items || []).length;
          return (
            <div key={k} style={{ background: "var(--ink-surface-2)", borderRadius: 10, padding: "12px 13px" }}>
              <div className="row between center" style={{ gap: 8, marginBottom: 10 }}>
                <span style={{ fontWeight: 600, fontSize: 13, color: "var(--on-ink)" }}>{titleCase(k)}</span>
                {exCount > 0 && (
                  <span style={{ fontWeight: 600, fontSize: 9.5, borderRadius: "var(--r-pill)", padding: "3px 8px", background: "#33211f", color: "#e09a86" }}>
                    {exCount} excluded
                  </span>
                )}
              </div>
              <div className="policy-grid-3">
                <Field label="sub-limit" affix="₹" value={c.sub_limit} onChange={(v) => setPolicyValue(`opd_categories.${k}.sub_limit`, v)} />
                <Field label="co-pay %" value={c.copay_percent ?? 0} onChange={(v) => setPolicyValue(`opd_categories.${k}.copay_percent`, v)} />
                <Field label="network %" value={c.network_discount_percent ?? 0} onChange={(v) => setPolicyValue(`opd_categories.${k}.network_discount_percent`, v)} />
              </div>
              <div className="row between center" style={{ marginTop: 11 }}>
                <span style={{ fontSize: 11, color: "var(--on-ink-soft)" }}>Requires pre-authorisation</span>
                <button
                  className={`toggle sm${c.requires_pre_auth ? " on" : ""}`}
                  aria-pressed={!!c.requires_pre_auth}
                  aria-label="Toggle pre-authorisation"
                  onClick={() => setPolicyValue(`opd_categories.${k}.requires_pre_auth`, !c.requires_pre_auth)}
                >
                  <span className="knob" />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--ink-surface-2)" }}>
        <div style={{ fontWeight: 600, fontSize: 12, color: "var(--on-ink)", marginBottom: 8 }}>predicted path for this claim</div>
        <span className="pill status-pill" style={{ background: STATUS_COLORS[dec.status] }}>{statusLabel(dec.status)}</span>
        <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--on-ink-soft)", marginTop: 10 }}>{dec.message}</div>
      </div>
    </div>
  );
}

function Field({ label, value, affix, onChange }: { label: string; value?: number; affix?: string; onChange: (v: number) => void }) {
  return (
    <label className="policy-stat">
      <span className="lbl">{label}</span>
      <span className="policy-field">
        {affix && <span className="affix">{affix}</span>}
        <input
          type="text"
          inputMode="numeric"
          value={value ?? 0}
          onChange={(e) => onChange(Number(e.target.value.replace(/[^0-9]/g, "")) || 0)}
        />
      </span>
    </label>
  );
}
