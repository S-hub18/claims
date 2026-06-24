"use client";

import { confBand } from "./format";
import type { Decision, Status } from "./types";
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

interface BackendDecision {
  claim_id: string;
  status: string;
  approved_amount?: string | null;
  rejection_reasons?: string[];
  messages?: string[];
  notes?: string[];
  confidence?: number | null;
  fact_count?: number;
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
    const doc: SubmitDoc = {
      file_id: d.file_id,
      file_name: d.file_name,
      actual_type: d.doc_type ?? undefined,
      quality: d.quality,
      patient_name_on_doc: d.patient_name_on_doc ?? undefined,
    };
    if (d.content) doc.content = d.content;
    const up = sessionUploads[d.file_id];
    if (up) {
      doc.data = up.data;
      doc.mime_type = up.mime;
    }
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
  };
}
