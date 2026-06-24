"use client";

import { useEffect } from "react";
import { fmt } from "@/lib/format";
import { publicUrlFor, type EmployeeDocument } from "@/lib/db";
import { PdfCanvas } from "./PdfCanvas";

interface LineItem {
  description?: string;
  amount?: number;
}

export function DocPreview({ doc, onClose }: { doc: EmployeeDocument; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const url = doc.storage_path ? publicUrlFor(doc.storage_path) : null;
  const mime = doc.mime_type || "";
  // mime_type is authoritative — several on-file docs are PDFs with a legacy
  // .jpg file_name. PDF must win and the two must be mutually exclusive, or both
  // branches render (and WebKit shows a PDF inside <img>, doubling the page).
  const isPdf = mime === "application/pdf" || (!mime && /\.pdf$/i.test(doc.file_name));
  const isImage = !isPdf && (mime.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(doc.file_name));
  const content = (doc.content || null) as Record<string, unknown> | null;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 300,
        background: "rgba(38,37,30,0.55)",
        backdropFilter: "blur(2px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{ width: "min(640px, 100%)", maxHeight: "86vh", overflow: "auto", padding: 0 }}
      >
        {/* header */}
        <div
          className="row between center"
          style={{ padding: "16px 20px", borderBottom: "1px solid var(--hairline)", position: "sticky", top: 0, background: "var(--surface-card)" }}
        >
          <div className="col" style={{ gap: 2 }}>
            <span style={{ fontWeight: 600, fontSize: 15, color: "var(--ink)" }}>{doc.file_name}</span>
            <span className="section-label">
              {(doc.doc_type || "document").replace(/_/g, " ").toLowerCase()}
              {doc.is_user_uploaded ? " · your upload" : " · on file"}
              {doc.quality && doc.quality !== "GOOD" ? ` · ${doc.quality.toLowerCase()}` : ""}
            </span>
          </div>
          <button className="btn btn-secondary" onClick={onClose} style={{ padding: "6px 12px" }}>
            Close
          </button>
        </div>

        <div className="col" style={{ padding: 20, gap: 16 }}>
          {/* Prefer the genuine file when one exists — that IS the document to
              validate. Images embed directly; PDFs use <object> (more forgiving
              than <iframe> across browsers) with a guaranteed open-in-tab link,
              so the preview is never a blank box even when inline rendering is
              blocked (e.g. Safari with cross-origin PDFs). The structured
              DocSheet is only a fallback for docs that have no file, so we never
              show the same record twice. */}
          {url && isImage && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={url} alt={doc.file_name} style={{ width: "100%", borderRadius: "var(--r-md)", border: "1px solid var(--hairline)" }} />
          )}

          {url && isPdf && <PdfCanvas url={url} fileName={doc.file_name} />}

          {url && !isImage && !isPdf && (
            <a className="btn btn-primary" href={url} target="_blank" rel="noreferrer">
              Open file in new tab ↗
            </a>
          )}

          {!url && content && <DocSheet content={content} patient={doc.patient_name_on_doc} />}

          {!content && !url && (
            <div style={{ fontSize: 14, color: "var(--muted)" }}>
              No preview available for this document.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Renders structured extraction content as a readable "document" so the user can
// validate the on-file record is genuine and coherent.
function DocSheet({ content, patient }: { content: Record<string, unknown>; patient: string | null }) {
  const c = content as {
    hospital_name?: string;
    doctor_name?: string;
    doctor_registration?: string;
    patient_name?: string;
    date?: string;
    diagnosis?: string;
    treatment?: string;
    medicines?: string[];
    tests_ordered?: string[];
    line_items?: LineItem[];
    total?: number;
  };
  const items = c.line_items || [];

  return (
    <div
      style={{
        border: "1px solid var(--hairline)",
        borderRadius: "var(--r-md)",
        padding: 22,
        background: "var(--canvas-soft)",
      }}
    >
      <div className="row between" style={{ alignItems: "flex-start", marginBottom: 16 }}>
        <div style={{ fontWeight: 600, fontSize: 17, color: "var(--ink)" }}>
          {c.hospital_name || "—"}
        </div>
        {c.date && <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>{c.date}</span>}
      </div>

      <Field label="Patient" value={c.patient_name || patient || "—"} />
      {(c.doctor_name || c.doctor_registration) && (
        <Field
          label="Doctor"
          value={`${c.doctor_name || "—"}${c.doctor_registration ? ` · ${c.doctor_registration}` : ""}`}
        />
      )}
      {c.diagnosis && <Field label="Diagnosis" value={c.diagnosis} />}
      {c.treatment && <Field label="Treatment" value={c.treatment} />}
      {c.medicines && c.medicines.length > 0 && <Field label="Medicines" value={c.medicines.join(", ")} />}
      {c.tests_ordered && c.tests_ordered.length > 0 && (
        <Field label="Tests ordered" value={c.tests_ordered.join(", ")} />
      )}

      {items.length > 0 && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--hairline)" }}>
          <div className="section-label" style={{ marginBottom: 8 }}>
            Line items
          </div>
          {items.map((it, i) => (
            <div
              key={i}
              className="row between"
              style={{ padding: "7px 0", borderBottom: "1px solid var(--hairline-soft)", fontSize: 14 }}
            >
              <span style={{ color: "var(--ink)" }}>{it.description || "—"}</span>
              <span className="mono" style={{ color: "var(--ink)" }}>{fmt(it.amount ?? null)}</span>
            </div>
          ))}
          {c.total != null && (
            <div className="row between" style={{ padding: "11px 0 0", fontWeight: 600 }}>
              <span style={{ color: "var(--ink)" }}>Total</span>
              <span className="mono" style={{ color: "var(--primary)", fontSize: 16 }}>{fmt(c.total)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="row" style={{ gap: 12, padding: "5px 0", alignItems: "baseline" }}>
      <span style={{ width: 110, flex: "none", fontWeight: 600, fontSize: 12, color: "var(--muted)" }}>
        {label}
      </span>
      <span style={{ fontSize: 14, color: "var(--ink)", lineHeight: 1.45 }}>{value}</span>
    </div>
  );
}
