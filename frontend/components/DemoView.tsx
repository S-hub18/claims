"use client";

import { useState } from "react";
import type { EngineProps } from "./ui";
import { Select, STATUS_COLORS } from "./ui";
import { DocPreview } from "./DocPreview";
import { iconFor } from "@/lib/format";
import { CATEGORY_OPTIONS } from "@/lib/api";
import type { EmployeeDocument } from "@/lib/db";
import type { Status } from "@/lib/types";

export function DemoView({ engine }: EngineProps) {
  const { state, patch, selectedEmployee, selectEmployee, uploadDoc, removeDoc, runDemo } = engine;
  const emp = selectedEmployee();
  const [preview, setPreview] = useState<EmployeeDocument | null>(null);

  return (
    <div className="rise">
      <div className="view-head">
        <div className="view-title">Mimic an employee, run a real claim</div>
        <div className="view-sub">
          Pick an employee from the roster, review the documents on file (or attach your own), set the
          treatment and amount, then run a live adjudication on the backend engine.
        </div>
      </div>

      <div className="row wrap" style={{ gap: 18, alignItems: "flex-start" }}>
        {/* profile picker — from Supabase */}
        <div className="card" style={{ flex: "none", width: 280, padding: 18 }}>
          <div className="section-label" style={{ marginBottom: 12 }}>
            Choose an employee
          </div>

          {state.employeesLoading ? (
            <div className="row center" style={{ gap: 10, padding: "10px 2px" }}>
              <span className="spinner" />
              <span style={{ fontSize: 13, color: "var(--muted)" }}>Loading roster…</span>
            </div>
          ) : state.employeesError ? (
            <div style={{ fontSize: 13, lineHeight: 1.5, color: "var(--st-rejected)" }}>
              {state.employeesError}
            </div>
          ) : (
            <div className="col" style={{ gap: 8 }}>
              {state.employees.map((p) => (
                <button
                  key={p.id}
                  className={`profile-row${p.id === state.selectedEmployeeId ? " active" : ""}`}
                  onClick={() => selectEmployee(p)}
                >
                  <span className="avatar" style={{ background: p.avatar_color || "var(--ink)" }}>
                    {p.initials || p.name.slice(0, 2).toUpperCase()}
                  </span>
                  <span className="col" style={{ gap: 1, minWidth: 0 }}>
                    <span style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)" }}>{p.name}</span>
                    <span
                      style={{ fontWeight: 500, fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 170 }}
                      title={p.case_name || undefined}
                    >
                      <span className="mono">{p.case_id}</span> · {p.case_name}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}

          <div
            style={{
              marginTop: 14,
              paddingTop: 14,
              borderTop: "1px solid var(--hairline-soft)",
              fontSize: 12,
              lineHeight: 1.5,
              color: "var(--muted-soft)",
            }}
          >
            Roster &amp; documents are fetched live from Supabase. Run adjudication submits to the
            backend engine.
          </div>
        </div>

        {/* setup */}
        <div id="claim-setup" className="card" style={{ flex: 1, minWidth: 0, scrollMarginTop: 90 }}>
          {!emp ? (
            <div style={{ fontSize: 14, color: "var(--muted)" }}>Select an employee to begin.</div>
          ) : (
            <>
              <div className="row between center wrap" style={{ gap: 12 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 22, color: "var(--ink)" }}>{emp.name}</div>
                  <div style={{ fontWeight: 500, fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
                    <span className="mono">{emp.member_id}</span> · Policy {emp.policy_id} ·{" "}
                    {emp.default_treatment_label}
                  </div>
                </div>
                {emp.expected_status && (
                  <span
                    className="pill status-pill"
                    style={{ background: STATUS_COLORS[(emp.expected_status as Status) || "MANUAL_REVIEW"] }}
                  >
                    Expects {emp.expected_status.replace("_", " ")}
                  </span>
                )}
              </div>

              {(emp.case_id || emp.expected_note) && (
                <div
                  style={{ marginTop: 12, padding: "11px 13px", background: "var(--canvas-soft)", border: "1px solid var(--hairline)", borderRadius: "var(--r-md)" }}
                >
                  <div style={{ fontWeight: 600, fontSize: 13, color: "var(--ink)" }}>
                    <span className="mono">{emp.case_id}</span> · {emp.case_name}
                  </div>
                  {emp.expected_note && (
                    <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--body)", marginTop: 4 }}>
                      Per the assignment: {emp.expected_note}
                    </div>
                  )}
                </div>
              )}

              <div className="section-label" style={{ marginTop: 22, marginBottom: 10 }}>
                Documents on file{" "}
                {state.docsLoading && <span style={{ color: "var(--muted-soft)" }}>· loading…</span>}
                {!state.docsLoading && state.employeeDocs.length > 0 && (
                  <span style={{ color: "var(--muted-soft)", textTransform: "none", letterSpacing: 0, fontWeight: 500 }}>
                    {" "}· click a document to preview
                  </span>
                )}
              </div>
              <div className="row wrap" style={{ gap: 10 }}>
                {state.employeeDocs.map((d) => (
                  <div
                    className={`doc${d.is_user_uploaded ? " yours" : ""}`}
                    key={d.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setPreview(d)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setPreview(d)}
                    style={{ cursor: "pointer" }}
                    title="Click to preview"
                  >
                    <span style={{ fontSize: 18 }}>{iconFor(d.file_name)}</span>
                    <span className="col">
                      <span className="doc-name">{d.file_name}</span>
                      <span
                        className="doc-meta"
                        style={d.is_user_uploaded ? { color: "var(--primary)" } : undefined}
                      >
                        {(d.size_kb ?? 0) + " KB"}
                        {d.doc_type ? " · " + d.doc_type.replace(/_/g, " ").toLowerCase() : ""}
                        {d.is_user_uploaded ? " · yours" : ""}
                      </span>
                    </span>
                    <button
                      className="doc-x"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeDoc(d);
                      }}
                      aria-label="Remove"
                      title={d.is_user_uploaded ? "Remove" : "Remove from this run"}
                    >
                      ×
                    </button>
                  </div>
                ))}
                <label className="attach" style={state.uploadingDoc ? { opacity: 0.6 } : undefined}>
                  {state.uploadingDoc ? "uploading…" : "+ attach your own"}
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

              <div className="row wrap" style={{ gap: 16, marginTop: 20 }}>
                <div style={{ flex: 1, minWidth: 150 }}>
                  <label className="field-label">Date of treatment</label>
                  <input
                    className="input"
                    type="date"
                    value={state.date}
                    onChange={(e) => patch({ date: e.target.value })}
                  />
                </div>
                <div style={{ flex: 1, minWidth: 150 }}>
                  <label className="field-label">Treatment type</label>
                  <Select value={state.treatment} onChange={(v) => patch({ treatment: v })}>
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
                    value={state.amount || ""}
                    placeholder="0"
                    onChange={(e) => {
                      const digits = e.target.value.replace(/[^0-9]/g, "");
                      patch({ amount: digits ? Number(digits) : 0 });
                    }}
                  />
                </div>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <label className="field-label">Hospital / provider</label>
                  <input
                    className="input"
                    type="text"
                    value={state.hospital}
                    placeholder="e.g. Apollo Hospitals"
                    onChange={(e) => patch({ hospital: e.target.value })}
                  />
                </div>
              </div>

              <div style={{ fontSize: 12, lineHeight: 1.45, color: "var(--muted-soft)", marginTop: 8 }}>
                Anything you leave blank is read from the uploaded documents.
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
                disabled={state.running || !emp}
                onClick={runDemo}
              >
                {state.running ? "Adjudicating…" : "Run adjudication →"}
              </button>
            </>
          )}
        </div>
      </div>

      {preview && <DocPreview doc={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}
