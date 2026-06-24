"use client";

import type { EngineProps } from "./ui";
import { Select } from "./ui";
import { PolicyPanel } from "./PolicyPanel";
import { CATEGORY_OPTIONS } from "@/lib/api";

const subLabel = { textTransform: "none", letterSpacing: 0, fontSize: 12, color: "var(--body)" } as const;

export function CustomView({ engine }: EngineProps) {
  const { state, patch, activePolicy, runCustom, onCustFiles, removeCustDoc } = engine;
  const P = activePolicy();
  const hospitals = P.network_hospitals || [];
  const inNet = hospitals.indexOf(state.custHospital) >= 0;

  return (
    <div className="rise">
      <div className="view-head">
        <div className="view-title">Build a brand-new claim from scratch</div>
        <div className="view-sub">
          Describe a claimant the engine has never seen — no stored profile, no history, no prior
          context. Enter the treatment details and the diagnosis, then run it: we submit everything to
          the backend and adjudicate this fresh claim against the policy.
        </div>
      </div>

      <div className="row wrap" style={{ gap: 18, alignItems: "flex-start" }}>
        <div className="card" style={{ flex: 1, minWidth: 320 }}>
          <div className="section-label" style={{ marginBottom: 12 }}>
            Member
          </div>
          <div className="row wrap" style={{ gap: 14 }}>
            <div style={{ flex: 2, minWidth: 180 }}>
              <label className="field-label" style={subLabel}>
                Full name
              </label>
              <input
                className="input"
                type="text"
                value={state.custName}
                placeholder="e.g. Rajesh Kumar"
                onChange={(e) => patch({ custName: e.target.value })}
              />
            </div>
            <div style={{ flex: 1, minWidth: 130 }}>
              <label className="field-label" style={subLabel}>
                Member ID
              </label>
              <input
                className="input"
                type="text"
                value={state.custId}
                placeholder="auto (guest)"
                onChange={(e) => patch({ custId: e.target.value })}
              />
            </div>
          </div>

          <div className="section-label" style={{ marginTop: 22, marginBottom: 10 }}>
            Documents
          </div>
          <label
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              onCustFiles(e.dataTransfer?.files || null);
            }}
          >
            <span style={{ fontSize: 26 }}>📎</span>
            <span style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)" }}>
              Drop files here or click to upload
            </span>
            <span style={{ fontWeight: 500, fontSize: 12, color: "var(--muted-soft)" }}>
              PDF or image · prescription, bill, lab report, discharge summary
            </span>
            <input
              type="file"
              multiple
              onChange={(e) => {
                onCustFiles(e.target.files);
                e.target.value = "";
              }}
              style={{ display: "none" }}
            />
          </label>
          {state.custDocs.length > 0 && (
            <div className="row wrap" style={{ gap: 10, marginTop: 12 }}>
              {state.custDocs.map((d, i) => (
                <div className="doc" key={i}>
                  <span style={{ fontSize: 18 }}>{d.icon}</span>
                  <span className="col">
                    <span className="doc-name">{d.name}</span>
                    <span className="doc-meta">{d.meta}</span>
                  </span>
                  <button className="doc-x" onClick={() => removeCustDoc(i)} aria-label="Remove">
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="row wrap" style={{ gap: 16, marginTop: 20 }}>
            <div style={{ flex: 1, minWidth: 150 }}>
              <label className="field-label">Date of treatment</label>
              <input
                className="input"
                type="date"
                value={state.custDate}
                onChange={(e) => patch({ custDate: e.target.value })}
              />
            </div>
            <div style={{ flex: 1, minWidth: 150 }}>
              <label className="field-label">Treatment type</label>
              <Select value={state.custTreatment} onChange={(v) => patch({ custTreatment: v })}>
                {CATEGORY_OPTIONS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </div>
            <div style={{ flex: 1, minWidth: 150 }}>
              <label className="field-label">Claimed amount (₹)</label>
              <input
                className="input"
                type="text"
                inputMode="numeric"
                value={state.custAmount || ""}
                placeholder="0"
                onChange={(e) => {
                  const digits = e.target.value.replace(/[^0-9]/g, "");
                  patch({ custAmount: digits ? Number(digits) : 0 });
                }}
              />
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <label className="field-label">Diagnosis / condition</label>
            <input
              className="input"
              type="text"
              value={state.custDiagnosis}
              placeholder="e.g. Acute bronchitis  ·  try “bariatric” or “cosmetic” to see an exclusion"
              onChange={(e) => patch({ custDiagnosis: e.target.value })}
            />
            <div style={{ fontSize: 12, lineHeight: 1.45, color: "var(--muted-soft)", marginTop: 6 }}>
              What the treating doctor wrote — the engine checks this against the policy’s coverage and
              exclusions.
            </div>
          </div>

          <div style={{ marginTop: 18 }}>
            <div className="row between center" style={{ marginBottom: 7 }}>
              <span className="section-label">Network hospital</span>
              <span
                className="tag"
                style={{ background: inNet ? "var(--st-approved)" : "var(--st-blocked)" }}
              >
                {inNet ? "In-network" : "Out-of-network"}
              </span>
            </div>
            <Select value={state.custHospital} onChange={(v) => patch({ custHospital: v })}>
              {[...hospitals, "Other (out-of-network)"].map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </Select>
            <div style={{ fontSize: 12, lineHeight: 1.45, color: "var(--muted-soft)", marginTop: 6 }}>
              {inNet
                ? "In-network provider — the category network discount applies."
                : "Out-of-network — no network discount is applied."}
            </div>
          </div>

          {state.apiError && (
            <div
              className="row"
              style={{ gap: 9, alignItems: "flex-start", marginTop: 16, padding: "11px 13px", background: "var(--st-rejected-soft)", border: "1px solid #f3cfc1", borderRadius: 10 }}
            >
              <span style={{ fontSize: 14 }}>⚠️</span>
              <span style={{ fontWeight: 500, fontSize: 13, lineHeight: 1.45, color: "var(--st-rejected)" }}>
                {state.apiError}
              </span>
            </div>
          )}

          <button
            className="btn btn-primary btn-lg"
            disabled={state.running || !state.custName.trim() || state.custAmount <= 0}
            onClick={runCustom}
          >
            {state.running ? "Adjudicating…" : "Run adjudication →"}
          </button>
        </div>

        <PolicyPanel engine={engine} />
      </div>
    </div>
  );
}
