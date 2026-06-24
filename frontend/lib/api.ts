"use client";

import { confBand } from "./format";
import type { Decision, Status, TraceFact } from "./types";
import type { Employee, EmployeeDocument } from "./db";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Backend claim categories (lowercase) ↔ display labels.
export const CATEGORY_OPTIONS: { value: string; label: string }[] = [
  { value: "consultation", label: "Consultation" },
  { value: "dental", label: "Dental" },
  { value: "diagnostic", label: "Diagnostic" },
  { value: "pharmacy", label: "Pharmacy" },
  { value: "vision", label: "Vision" },
  { value: "alternative_medicine", label: "Alternative Medicine" },
];

export const categoryLabel = (v: string): string =>
  CATEGORY_OPTIONS.find((o) => o.value === v)?.label ?? v;

// ── Backend request / response shapes (mirror app/api/schemas.py) ─────────────

interface SubmitDoc {
  file_id: string;
  file_name?: string;
  actual_type?: string;
  quality?: string;
  patient_name_on_doc?: string;
  content?: Record<string, unknown> | null;
  data?: string; // base64
  mime_type?: string;
}

export interface ClaimForm {
  category: string; // backend category (lowercase)
  treatmentDate: string;
  amount: number;
  hospital?: string | null;
  claimsHistory?: Array<Record<string, unknown>>;
  simulateFailure?: boolean;
}

interface BackendFact {
  seq: number;
  key: string;
  value: unknown;
  author: string;
  confidence?: number | null;
  degraded?: boolean;
  derived_from?: string[];
  reason?: string | null;
  t_ms?: number | null;
}

interface BackendDecision {
  claim_id: string;
  status: string;
  approved_amount?: string | null;
  rejection_reasons?: string[];
  messages?: string[];
  notes?: string[];
  confidence?: number | null;
  fact_count?: number;
  facts?: BackendFact[];
}

/** Map the backend's snake_case fact events to the UI's TraceFact shape. */
function toTraceFacts(raw: BackendFact[] | undefined): TraceFact[] {
  return (raw ?? []).map((f) => ({
    seq: f.seq,
    key: f.key,
    author: f.author,
    conf: f.confidence ?? null,
    degraded: f.degraded,
    reason: f.reason ?? undefined,
    value: f.value,
    derivedFrom: f.derived_from ?? [],
    tMs: f.t_ms ?? undefined,
  }));
}

/** In-memory base64 for documents uploaded this session, keyed by file_id. */
export type SessionUploads = Record<string, { data: string; mime: string }>;

export function buildSubmission(
  employee: Employee,
  docs: EmployeeDocument[],
  form: ClaimForm,
  sessionUploads: SessionUploads
) {
  const documents: SubmitDoc[] = docs.map((d) => {
    const up = sessionUploads[d.file_id];
    if (up) {
      // A freshly uploaded document is adjudicated from its OWN bytes only — never the
      // stale stored content or extraction hints. Otherwise the backend would re-use the
      // pre-baked Supabase extraction and the interviewer's upload would have no effect,
      // making the whole decision look hardcoded.
      return {
        file_id: d.file_id,
        file_name: d.file_name,
        data: up.data,
        mime_type: up.mime,
      };
    }
    const doc: SubmitDoc = {
      file_id: d.file_id,
      file_name: d.file_name,
      actual_type: d.doc_type ?? undefined,
      quality: d.quality,
      patient_name_on_doc: d.patient_name_on_doc ?? undefined,
    };
    if (d.content) doc.content = d.content;
    return doc;
  });

  const body: Record<string, unknown> = {
    member_id: employee.member_id,
    policy_id: employee.policy_id,
    claim_category: form.category,
    treatment_date: form.treatmentDate,
    claimed_amount: form.amount,
    // Always send the key verbatim (including "" when cleared) so the field is
    // authoritative: an empty hospital means "no network hospital" and drops the
    // discount, instead of the backend falling back to the bill's hospital.
    hospital_name: (form.hospital ?? "").trim(),
    documents,
  };
  if (form.claimsHistory && form.claimsHistory.length) body.claims_history = form.claimsHistory;
  if (form.simulateFailure) body.simulate_component_failure = true;
  return body;
}

async function submitClaim(body: unknown): Promise<string> {
  const res = await fetch(`${API_URL}/claims`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Backend returned ${res.status} on submit`);
  const data = (await res.json()) as { claim_id: string };
  return data.claim_id;
}

async function pollClaim(claimId: string, timeoutMs = 40000): Promise<BackendDecision> {
  const start = performance.now();
  let delay = 500;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const res = await fetch(`${API_URL}/claims/${claimId}`);
    if (!res.ok) throw new Error(`Backend returned ${res.status} while polling`);
    const data = (await res.json()) as BackendDecision;
    if (data.status && data.status !== "processing") return data;
    if (performance.now() - start > timeoutMs) {
      throw new Error("Timed out waiting for the adjudication decision.");
    }
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay + 250, 1500);
  }
}

const KNOWN: Status[] = ["APPROVED", "PARTIAL", "REJECTED", "MANUAL_REVIEW", "BLOCKED"];

export function mapDecision(
  b: BackendDecision,
  claimed: number,
  categoryLabel: string
): Decision {
  const status: Status = (KNOWN as string[]).includes(b.status)
    ? (b.status as Status)
    : "MANUAL_REVIEW";
  const approved = b.approved_amount != null ? Number(b.approved_amount) : null;
  const conf = b.confidence ?? null;
  const messages = b.messages ?? [];
  const reasons = b.rejection_reasons ?? [];
  const notes = [...(b.notes ?? [])];
  if (!(KNOWN as string[]).includes(b.status)) {
    notes.unshift(`Backend returned status "${b.status}".`);
  }
  const kind = status === "BLOCKED" ? "blocked" : reasons.length ? "reasons" : "financial";
  return {
    status,
    kind,
    message: messages[0] || reasons[0] || "Decision returned by the adjudication engine.",
    conf,
    confBand: confBand(conf),
    approved,
    claimed,
    lines: [],
    waterfall: [],
    issues: [],
    reasons,
    notes,
    category: categoryLabel,
    claimId: "#" + b.claim_id.slice(0, 4).toUpperCase(),
  };
}

export interface RunResult {
  decision: Decision;
  factCount: number;
  // The full ordered blackboard trace for this run. The demo/custom views ignore it;
  // the lifecycle/tester view renders it step by step. Empty if the backend is old.
  facts: TraceFact[];
}

export async function runBackendClaim(
  employee: Employee,
  docs: EmployeeDocument[],
  form: ClaimForm,
  sessionUploads: SessionUploads
): Promise<RunResult> {
  const body = buildSubmission(employee, docs, form, sessionUploads);
  const claimId = await submitClaim(body);
  const backend = await pollClaim(claimId);
  return {
    decision: mapDecision(backend, form.amount, form.category),
    factCount: backend.fact_count ?? 0,
    facts: toTraceFacts(backend.facts),
  };
}

// ── Custom claim — a fresh claimant the backend has no prior record of ─────────

/** A real document the user uploaded — sent as bytes for the backend to extract. */
export interface CustomUpload {
  file_id: string;
  file_name: string;
  data: string; // base64 (no data: prefix)
  mime: string;
}

export interface CustomClaimForm {
  name: string;
  memberId?: string;
  category: string; // backend category (lowercase)
  diagnosis?: string;
  treatmentDate: string;
  amount: number;
  hospital?: string | null;
  // Real uploaded documents. When present they are sent as bytes and the backend
  // (Claude) extracts them — doc type, patient, dates, amounts all read from the
  // file. When absent, the typed fields are synthesized into documents instead.
  uploads?: CustomUpload[];
  // Optional uploaded policy JSON. When provided it adjudicates this claim;
  // otherwise the backend's default policy is used as the backup.
  policyOverride?: Record<string, unknown> | null;
}

// Required document types per category — mirrors the policy's document_requirements.
// The system derives the document TYPES itself; the user never labels documents.
const REQUIRED_DOCS: Record<string, string[]> = {
  consultation: ["PRESCRIPTION", "HOSPITAL_BILL"],
  diagnostic: ["PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"],
  pharmacy: ["PRESCRIPTION", "PHARMACY_BILL"],
  dental: ["HOSPITAL_BILL"],
  vision: ["PRESCRIPTION", "HOSPITAL_BILL"],
  alternative_medicine: ["PRESCRIPTION", "HOSPITAL_BILL"],
};

function shortToken(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID().slice(0, 6).toUpperCase();
  return Math.random().toString(36).slice(2, 8).toUpperCase();
}

// Offline (no OCR) the engine reads documents from their structured content, so we
// build the required documents from the user's typed facts. The claim is processed
// entirely from this input — no stored employee, history, or prior context.
function synthesizeDocuments(form: CustomClaimForm): SubmitDoc[] {
  const types = REQUIRED_DOCS[form.category] ?? ["PRESCRIPTION", "HOSPITAL_BILL"];
  const patient = form.name.trim() || "Claimant";
  const hospital = (form.hospital ?? "").trim();
  const label = categoryLabel(form.category);
  return types.map((t, i): SubmitDoc => {
    const base = {
      file_id: `custom-${t.toLowerCase()}-${i}`,
      file_name: `${t.toLowerCase()}.pdf`,
      actual_type: t,
      quality: "GOOD",
    };
    if (t === "PRESCRIPTION") {
      return {
        ...base,
        content: {
          patient_name: patient,
          date: form.treatmentDate,
          doctor_name: "Dr. A. Mehta",
          doctor_registration: "MH/45678/2015",
          diagnosis: form.diagnosis?.trim() || `${label} consultation`,
          medicines: [],
        },
      };
    }
    if (t === "LAB_REPORT") {
      return {
        ...base,
        content: {
          patient_name: patient,
          hospital_name: hospital,
          date: form.treatmentDate,
          tests_ordered: [`${label} panel`],
        },
      };
    }
    // HOSPITAL_BILL / PHARMACY_BILL
    return {
      ...base,
      content: {
        patient_name: patient,
        hospital_name: hospital,
        date: form.treatmentDate,
        total: form.amount,
        line_items: [{ description: label, amount: form.amount }],
      },
    };
  });
}

export async function runCustomClaim(form: CustomClaimForm): Promise<RunResult> {
  const body: Record<string, unknown> = {
    // A member ID that is not on the policy roster → the backend resolves it as
    // "not found" and skips waiting-period / member-identity checks: a genuinely
    // fresh claimant, processed from the submitted facts alone.
    member_id: form.memberId?.trim() || `GUEST-${shortToken()}`,
    policy_id: "PLUM_GHI_2024",
    claim_category: form.category,
    treatment_date: form.treatmentDate,
    claimed_amount: form.amount,
    hospital_name: (form.hospital ?? "").trim(),
    // Real uploads → send the bytes for Claude to read; else synthesize from fields.
    documents:
      form.uploads && form.uploads.length
        ? form.uploads.map((u) => ({
            file_id: u.file_id,
            file_name: u.file_name,
            data: u.data,
            mime_type: u.mime,
          }))
        : synthesizeDocuments(form),
  };
  if (form.policyOverride) body.policy_override = form.policyOverride;
  const claimId = await submitClaim(body);
  const backend = await pollClaim(claimId);
  return {
    decision: mapDecision(backend, form.amount, categoryLabel(form.category)),
    factCount: backend.fact_count ?? 0,
    facts: toTraceFacts(backend.facts),
  };
}
