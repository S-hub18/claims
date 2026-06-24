"use client";

import { supabase, CLAIM_DOCS_BUCKET } from "./supabase";

// ── Row shapes (mirror public.employees / public.employee_documents) ──────────

export interface Employee {
  id: string;
  member_id: string;
  name: string;
  policy_id: string;
  initials: string | null;
  avatar_color: string | null;
  enrolled_months: number;
  default_category: string; // backend category (lowercase)
  default_treatment_label: string;
  default_amount: number;
  default_hospital: string | null;
  badge: string | null;
  scenario: string | null;
  sort_order: number;
  // assignment test-scenario metadata
  case_id: string | null;
  case_name: string | null;
  treatment_date: string | null;
  claims_history: Array<Record<string, unknown>>;
  simulate_failure: boolean;
  expected_status: string | null;
  expected_note: string | null;
}

export interface EmployeeDocument {
  id: string;
  employee_id: string;
  file_id: string;
  file_name: string;
  doc_type: string | null;
  quality: string;
  size_kb: number | null;
  patient_name_on_doc: string | null;
  content: Record<string, unknown> | null;
  storage_path: string | null;
  mime_type: string | null;
  is_user_uploaded: boolean;
  created_at: string;
}

// ── Reads ─────────────────────────────────────────────────────────────────────

export async function fetchEmployees(): Promise<Employee[]> {
  const { data, error } = await supabase
    .from("employees")
    .select("*")
    .order("sort_order", { ascending: true });
  if (error) throw new Error(error.message);
  return (data ?? []) as Employee[];
}

export async function fetchEmployeeDocuments(employeeId: string): Promise<EmployeeDocument[]> {
  const { data, error } = await supabase
    .from("employee_documents")
    .select("*")
    .eq("employee_id", employeeId)
    .order("created_at", { ascending: true });
  if (error) throw new Error(error.message);
  return (data ?? []) as EmployeeDocument[];
}

// ── Writes (user-uploaded documents) ──────────────────────────────────────────

export interface UploadedDoc {
  row: EmployeeDocument;
  /** base64 (no data: prefix) kept in memory so this session's run can send bytes. */
  base64: string;
  mime: string;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function inferDocType(name: string): string {
  const n = name.toLowerCase();
  if (n.match(/presc/)) return "PRESCRIPTION";
  if (n.match(/discharge|summary/)) return "DISCHARGE_SUMMARY";
  if (n.match(/lab|diag|report/)) return "LAB_REPORT";
  if (n.match(/pharm/)) return "PHARMACY_INVOICE";
  return "HOSPITAL_BILL";
}

function uniqueToken(): string {
  // Unique per upload so the storage path never collides — keeps every upload a
  // plain INSERT (allowed by the anon policy) instead of an upsert/UPDATE, which
  // has no RLS policy and was failing with "violates row-level security policy".
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID().slice(0, 8);
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}

export async function uploadEmployeeDocument(
  employee: Employee,
  file: File
): Promise<UploadedDoc> {
  const fileId = `upload-${employee.member_id}-${uniqueToken()}`;
  const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
  const storagePath = `${employee.member_id}/${fileId}-${safeName}`;
  const mime = file.type || "application/octet-stream";

  const { error: upErr } = await supabase.storage
    .from(CLAIM_DOCS_BUCKET)
    .upload(storagePath, file, { upsert: false, contentType: mime });
  if (upErr) throw new Error(`Storage upload failed: ${upErr.message}`);

  const insert = {
    employee_id: employee.id,
    file_id: fileId,
    file_name: file.name,
    doc_type: inferDocType(file.name),
    quality: "GOOD",
    size_kb: Math.max(1, Math.round(file.size / 1024)),
    patient_name_on_doc: employee.name,
    storage_path: storagePath,
    mime_type: mime,
    is_user_uploaded: true,
  };
  const { data, error } = await supabase
    .from("employee_documents")
    .insert(insert)
    .select("*")
    .single();
  if (error) throw new Error(`DB insert failed: ${error.message}`);

  const base64 = await fileToBase64(file);
  return { row: data as EmployeeDocument, base64, mime };
}

export function publicUrlFor(storagePath: string): string {
  return supabase.storage.from(CLAIM_DOCS_BUCKET).getPublicUrl(storagePath).data.publicUrl;
}

export async function deleteEmployeeDocument(doc: EmployeeDocument): Promise<void> {
  if (doc.storage_path) {
    await supabase.storage.from(CLAIM_DOCS_BUCKET).remove([doc.storage_path]);
  }
  const { error } = await supabase.from("employee_documents").delete().eq("id", doc.id);
  if (error) throw new Error(error.message);
}
