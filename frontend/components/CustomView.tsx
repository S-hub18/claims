"use client";

import type { EngineProps } from "./ui";
import { Select } from "./ui";
import { PolicyPanel } from "./PolicyPanel";
import { TREATMENTS } from "@/lib/profiles";

export function CustomView({ engine }: EngineProps) {
  const { state, patch, activePolicy, runCustom, onCustFiles, removeCustDoc } = engine;
  const P = activePolicy();
  const hospitals = P.network_hospitals || [];
  const inNet = hospitals.indexOf(state.custHospital) >= 0;

  return (
    <div className="rise">
      <div className="view-head">
        <div className="view-title">Build your own claimant &amp; documents</div>
        <div className="view-sub">
          Name a member, upload real documents, pick a treatment and amount, then upload the policy
          on the right — we parse it live and adjudicate this claim against it.
        </div>
      </div>

      <div className="row wrap" style={{ gap: 18, alignItems: "flex-start" }}>
        <div className="card" style={{ flex: 1, minWidth: 320 }}>
          <div className="section-label" style={{ marginBottom: 12 }}>
            Member
          </div>
          <div className="row wrap" style={{ gap: 14 }}>
            <div style={{ flex: 2, minWidth: 180 }}>
              <label className="field-label" style={{ textTransform: "none", letterSpacing: 0, fontSize: 12, color: "var(--body)" }}>
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
              <label className="field-label" style={{ textTransform: "none", letterSpacing: 0, fontSize: 12, color: "var(--body)" }}>
                Member ID
              </label>
              <input
                className="input"
                type="text"
                value={state.custId}
                placeholder="auto"
                onChange={(e) => patch({ custId: e.target.value })}
              />
            </div>
          </div>

          <div className="section-label">Documents</div>
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
              <label className="field-label">Date of admission</label>
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
                {TREATMENTS.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </Select>
            </div>
            <div style={{ flex: 1, minWidth: 150 }}>
              <label className="field-label">Claimed amount (₹)</label>
              <input
                className="input"
                type="number"
                value={state.custAmount}
                onChange={(e) => patch({ custAmount: Number(e.target.value) || 0 })}
              />
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

          <button className="btn btn-primary btn-lg" disabled={state.running} onClick={runCustom}>
            {state.running ? "Adjudicating…" : "Run adjudication →"}
          </button>
        </div>

        <PolicyPanel engine={engine} />
      </div>
    </div>
  );
}
