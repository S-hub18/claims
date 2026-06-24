"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fmt, filesToObjs } from "./format";
import { DEFAULT_POLICY } from "./policy";
import {
  fetchEmployees,
  fetchEmployeeDocuments,
  uploadEmployeeDocument,
  deleteEmployeeDocument,
  type Employee,
  type EmployeeDocument,
} from "./db";
import {
  runBackendClaim,
  runCustomClaim,
  categoryLabel,
  type SessionUploads,
  type CustomUpload,
} from "./api";
import type {
  Decision,
  DocFile,
  HistoryRow,
  Policy,
  Status,
  TraceFact,
  View,
} from "./types";

export interface EngineState {
  view: View;
  dev: boolean;
  // demo — employees + docs come from Supabase
  employees: Employee[];
  employeesLoading: boolean;
  employeesError: string | null;
  selectedEmployeeId: string | null;
  employeeDocs: EmployeeDocument[];
  docsLoading: boolean;
  uploadingDoc: boolean;
  sessionUploads: SessionUploads;
  date: string;
  treatment: string; // backend category (lowercase)
  amount: number;
  hospital: string;
  apiError: string | null;
  // custom
  custName: string;
  custId: string;
  custDocs: DocFile[];
  custUploads: CustomUpload[];
  custDate: string;
  custTreatment: string; // backend category (lowercase)
  custDiagnosis: string;
  custAmount: number;
  custHospital: string;
  // policy + dev config
  policy: Policy | null;
  policyUploaded: boolean;
  policyError: string | null;
  subLimitScope: "covered" | "billed";
  confThreshold: number;
  policyVersion: string;
  disabled: Record<string, boolean>;
  // run
  running: boolean;
  hasDecision: boolean;
  decision: Decision | null;
  facts: TraceFact[];
  agentsFired: number;
  elapsed: number;
  lastSource: "demo" | "custom";
  // history
  history: HistoryRow[];
  // eval / lifecycle — runs the SELECTED demo profile (same claim flow) but keeps the
  // full trace + timing so a tester can validate every step the engine takes
  evalBusy: boolean;
  evalRan: boolean;
  evalDecision: Decision | null;
  evalFacts: TraceFact[];
  evalElapsed: number;
  evalError: string | null;
  // chrome
  toast: { status: Status; sub: string } | null;
  traceOpen: boolean;
}

const INITIAL: EngineState = {
  view: "demo",
  dev: false,
  employees: [],
  employeesLoading: true,
  employeesError: null,
  selectedEmployeeId: null,
  employeeDocs: [],
  docsLoading: false,
  uploadingDoc: false,
  sessionUploads: {},
  date: "2024-09-15",
  treatment: "consultation",
  amount: 4500,
  hospital: "",
  apiError: null,
  custName: "",
  custId: "",
  custDocs: [],
  custUploads: [],
  custDate: "2024-09-18",
  custTreatment: "consultation",
  custDiagnosis: "",
  custAmount: 4500,
  custHospital: "Apollo Hospitals",
  policy: null,
  policyUploaded: false,
  policyError: null,
  subLimitScope: "covered",
  confThreshold: 0.7,
  policyVersion: "v9",
  disabled: {},
  running: false,
  hasDecision: false,
  decision: null,
  facts: [],
  agentsFired: 0,
  elapsed: 0,
  lastSource: "demo",
  history: [],
  evalBusy: false,
  evalRan: false,
  evalDecision: null,
  evalFacts: [],
  evalElapsed: 0,
  evalError: null,
  toast: null,
  traceOpen: false,
};

const TOAST_TIP: Record<Status, string> = {
  APPROVED: "Payout approved and on its way.",
  PARTIAL: "Part of the claim is payable — see the breakdown.",
  REJECTED: "Claim rejected — reasons listed below.",
  MANUAL_REVIEW: "Sent to a human reviewer.",
  BLOCKED: "Fix the listed items and resubmit once.",
};

let claimSeq = 0xa10;
function newClaimId() {
  claimSeq = (claimSeq + 0x137) & 0xffff;
  return "#" + claimSeq.toString(16).toUpperCase().padStart(4, "0");
}

let custUploadSeq = 0;
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}


export function useClaimEngine() {
  const [s, setS] = useState<EngineState>(INITIAL);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearTimers = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  }, []);

  const patch = useCallback(
    (p: Partial<EngineState> | ((st: EngineState) => Partial<EngineState>)) => {
      setS((st) => ({ ...st, ...(typeof p === "function" ? p(st) : p) }));
    },
    []
  );

  const activePolicy = useCallback((): Policy => s.policy || DEFAULT_POLICY, [s.policy]);

  // ── employee loading (Supabase) ─────────────────────────────────────────────
  const loadDocs = useCallback(
    async (employeeId: string) => {
      patch({ docsLoading: true });
      try {
        const docs = await fetchEmployeeDocuments(employeeId);
        patch({ employeeDocs: docs, docsLoading: false });
      } catch (e) {
        patch({ docsLoading: false, employeesError: (e as Error).message });
      }
    },
    [patch]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const employees = await fetchEmployees();
        if (cancelled) return;
        const first = employees[0] ?? null;
        patch({
          employees,
          employeesLoading: false,
          employeesError: employees.length ? null : "No employees found in the database.",
          selectedEmployeeId: first?.id ?? null,
          treatment: first?.default_category ?? "consultation",
          amount: first ? Number(first.default_amount) : 4500,
          date: first?.treatment_date ?? "2024-11-01",
          hospital: first?.default_hospital ?? "",
        });
        if (first) loadDocs(first.id);
      } catch (e) {
        if (!cancelled) patch({ employeesLoading: false, employeesError: (e as Error).message });
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => clearTimers(), [clearTimers]);

  const selectedEmployee = useCallback(
    (): Employee | null => s.employees.find((e) => e.id === s.selectedEmployeeId) ?? null,
    [s.employees, s.selectedEmployeeId]
  );

  const selectEmployee = useCallback(
    (emp: Employee) => {
      clearTimers();
      patch({
        selectedEmployeeId: emp.id,
        treatment: emp.default_category,
        amount: Number(emp.default_amount),
        date: emp.treatment_date ?? "2024-11-01",
        hospital: emp.default_hospital ?? "",
        employeeDocs: [],
        sessionUploads: {},
        running: false,
        hasDecision: false,
        decision: null,
        facts: [],
        elapsed: 0,
        toast: null,
        apiError: null,
      });
      loadDocs(emp.id);
    },
    [clearTimers, patch, loadDocs]
  );

  const uploadDoc = useCallback(
    async (files: FileList | null) => {
      const emp = s.employees.find((e) => e.id === s.selectedEmployeeId);
      if (!emp || !files || files.length === 0) return;
      patch({ uploadingDoc: true, apiError: null });
      try {
        for (const file of Array.from(files)) {
          const { row, base64, mime } = await uploadEmployeeDocument(emp, file);
          patch((st) => ({
            employeeDocs: [...st.employeeDocs, row],
            sessionUploads: { ...st.sessionUploads, [row.file_id]: { data: base64, mime } },
          }));
        }
        patch({ uploadingDoc: false });
      } catch (e) {
        patch({ uploadingDoc: false, apiError: (e as Error).message });
      }
    },
    [patch, s.employees, s.selectedEmployeeId]
  );

  const removeDoc = useCallback(
    async (doc: EmployeeDocument) => {
      patch((st) => {
        const su = { ...st.sessionUploads };
        delete su[doc.file_id];
        return { employeeDocs: st.employeeDocs.filter((d) => d.id !== doc.id), sessionUploads: su };
      });
      // Only a doc the interviewer uploaded this session is deleted from Supabase. A seed
      // doc is removed from THIS run's claim only — its Supabase row is left intact so the
      // profile is unchanged on the next run (lets them safely drop the bad doc and retry).
      if (!doc.is_user_uploaded) return;
      try {
        await deleteEmployeeDocument(doc);
      } catch (e) {
        patch({ apiError: (e as Error).message });
      }
    },
    [patch]
  );

  // ── history ─────────────────────────────────────────────────────────────────
  const pushHistory = useCallback(
    (dec: Decision, member: string, category: string, elapsed: number) => {
      const row: HistoryRow = {
        claimId: dec.claimId || newClaimId(),
        member,
        category,
        status: dec.status,
        approved: fmt(dec.approved),
        conf: dec.conf != null ? dec.conf.toFixed(2) : "—",
        time: elapsed.toFixed(1) + "s",
      };
      patch((st) => ({ history: [row, ...st.history].slice(0, 8) }));
    },
    [patch]
  );

  // ── DEMO run — through the FastAPI backend ──────────────────────────────────
  const runDemo = useCallback(async () => {
    if (s.running) return;
    const emp = s.employees.find((e) => e.id === s.selectedEmployeeId);
    if (!emp) return;
    clearTimers();
    patch({
      running: true,
      hasDecision: false,
      decision: null,
      facts: [],
      agentsFired: 0,
      elapsed: 0,
      toast: null,
      traceOpen: false,
      lastSource: "demo",
      apiError: null,
    });
    const t0 = performance.now();
    try {
      const { decision, factCount } = await runBackendClaim(
        emp,
        s.employeeDocs,
        {
          category: s.treatment,
          treatmentDate: s.date,
          amount: s.amount,
          // Send the field verbatim — no fallback to the case default, so
          // clearing/changing the hospital actually changes the decision.
          hospital: s.hospital,
          claimsHistory: emp.claims_history,
          simulateFailure: emp.simulate_failure,
        },
        s.sessionUploads
      );
      const elapsed = (performance.now() - t0) / 1000;
      patch({
        running: false,
        hasDecision: true,
        decision,
        agentsFired: factCount,
        elapsed,
        toast: { status: decision.status, sub: TOAST_TIP[decision.status] || "" },
      });
      pushHistory(decision, emp.name, categoryLabel(s.treatment), elapsed);
      timers.current.push(setTimeout(() => patch({ toast: null }), 4400));
    } catch (e) {
      const msg = (e as Error).message || String(e);
      patch({
        running: false,
        apiError: msg,
        toast: { status: "MANUAL_REVIEW", sub: "Could not reach the adjudication backend." },
      });
      timers.current.push(setTimeout(() => patch({ toast: null }), 4400));
    }
  }, [
    s.running,
    s.employees,
    s.selectedEmployeeId,
    s.employeeDocs,
    s.treatment,
    s.date,
    s.amount,
    s.hospital,
    s.sessionUploads,
    clearTimers,
    patch,
    pushHistory,
  ]);

  // ── CUSTOM run — a fresh claimant, adjudicated on the backend ────────────────
  // No stored employee, history, or prior context: the typed facts are submitted
  // to the engine and processed as if seen for the first time.
  const runCustom = useCallback(async () => {
    if (s.running) return;
    clearTimers();
    patch({
      running: true,
      hasDecision: false,
      decision: null,
      facts: [],
      agentsFired: 0,
      elapsed: 0,
      toast: null,
      traceOpen: false,
      lastSource: "custom",
      apiError: null,
    });
    const t0 = performance.now();
    try {
      const hospital = s.custHospital.startsWith("Other") ? "" : s.custHospital;
      const { decision, factCount } = await runCustomClaim({
        name: s.custName,
        memberId: s.custId,
        category: s.custTreatment,
        diagnosis: s.custDiagnosis,
        treatmentDate: s.custDate,
        amount: s.custAmount,
        hospital,
        // Real uploaded documents drive the claim when present (Claude reads them).
        uploads: s.custUploads?.length ? s.custUploads : undefined,
        // Only override when the user actually uploaded a policy — otherwise the
        // backend falls back to its default policy as the backup.
        policyOverride: s.policyUploaded
          ? (s.policy as unknown as Record<string, unknown>)
          : undefined,
      });
      const elapsed = (performance.now() - t0) / 1000;
      patch({
        running: false,
        hasDecision: true,
        decision,
        agentsFired: factCount,
        elapsed,
        toast: { status: decision.status, sub: TOAST_TIP[decision.status] || "" },
      });
      pushHistory(decision, s.custName || "Custom claimant", categoryLabel(s.custTreatment), elapsed);
      timers.current.push(setTimeout(() => patch({ toast: null }), 4400));
    } catch (e) {
      const msg = (e as Error).message || String(e);
      patch({
        running: false,
        apiError: msg,
        toast: { status: "MANUAL_REVIEW", sub: "Could not reach the adjudication backend." },
      });
      timers.current.push(setTimeout(() => patch({ toast: null }), 4400));
    }
  }, [
    s.running,
    s.custName,
    s.custId,
    s.custTreatment,
    s.custDiagnosis,
    s.custDate,
    s.custDiagnosis,
    s.custAmount,
    s.custHospital,
    s.custUploads,
    s.policy,
    s.policyUploaded,
    clearTimers,
    patch,
    pushHistory,
  ]);

  const rerun = useCallback(() => {
    if (s.lastSource === "custom") runCustom();
    else runDemo();
  }, [s.lastSource, runCustom, runDemo]);

  const resubmit = useCallback(() => {
    clearTimers();
    patch({ hasDecision: false, decision: null, facts: [], toast: null });
  }, [clearTimers, patch]);

  const setView = useCallback(
    (v: View) => {
      clearTimers();
      patch({
        view: v,
        running: false,
        hasDecision: false,
        decision: null,
        facts: [],
        elapsed: 0,
        toast: null,
        traceOpen: false,
      });
    },
    [clearTimers, patch]
  );

  // custom file handlers — capture the File objects synchronously (the onChange
  // caller clears the input right after), then read their bytes to base64 so the
  // real uploaded documents can be sent to the backend for Claude to extract.
  const onCustFiles = (fileList: FileList | null) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const display = filesToObjs(files); // {name, icon, meta} for the UI list
    Promise.all(files.map((f) => fileToBase64(f)))
      .then((b64s) => {
        const uploads: CustomUpload[] = files.map((f, i) => ({
          file_id: `custom-up-${++custUploadSeq}`,
          file_name: f.name,
          data: b64s[i],
          mime: f.type || "application/octet-stream",
        }));
        patch((st) => ({
          custDocs: [...(st.custDocs || []), ...display],
          custUploads: [...(st.custUploads || []), ...uploads],
        }));
      })
      .catch((e) => patch({ apiError: (e as Error).message }));
  };
  const removeCustDoc = (i: number) =>
    patch((st) => ({
      custDocs: (st.custDocs || []).filter((_, j) => j !== i),
      custUploads: (st.custUploads || []).filter((_, j) => j !== i),
    }));

  const onPolicyFile = (file: File | null) => {
    if (!file) return;
    file
      .text()
      .then((txt) => {
        try {
          const p = JSON.parse(txt) as Policy;
          patch({ policy: p, policyUploaded: true, policyError: null });
        } catch {
          patch({ policyError: "Could not parse " + file.name + " — expected valid JSON." });
        }
      })
      .catch(() => patch({ policyError: "Could not read " + file.name + "." }));
  };

  // ── eval / lifecycle — run the SELECTED demo profile, keep the full trace ──────
  // Same claim flow as the demo view (same employee, documents, and form fields), but
  // we capture every fact the engine posts plus per-step timing, so a tester can watch
  // and validate each step instead of only seeing the final decision.
  const runEval = useCallback(async () => {
    if (s.evalBusy) return;
    const emp = s.employees.find((e) => e.id === s.selectedEmployeeId);
    if (!emp) return;
    patch({ evalBusy: true, evalError: null, evalRan: false });
    const t0 = performance.now();
    try {
      const { decision, facts } = await runBackendClaim(
        emp,
        s.employeeDocs,
        {
          category: s.treatment,
          treatmentDate: s.date,
          amount: s.amount,
          hospital: s.hospital,
          claimsHistory: emp.claims_history,
          simulateFailure: emp.simulate_failure,
        },
        s.sessionUploads
      );
      patch({
        evalBusy: false,
        evalRan: true,
        evalDecision: decision,
        evalFacts: facts,
        evalElapsed: (performance.now() - t0) / 1000,
      });
    } catch (e) {
      patch({ evalBusy: false, evalError: (e as Error).message || String(e) });
    }
  }, [
    s.evalBusy,
    s.employees,
    s.selectedEmployeeId,
    s.employeeDocs,
    s.treatment,
    s.date,
    s.amount,
    s.hospital,
    s.sessionUploads,
    patch,
  ]);

  return {
    state: s,
    patch,
    activePolicy,
    selectedEmployee,
    selectEmployee,
    uploadDoc,
    removeDoc,
    setView,
    toggleDev: () => patch((st) => ({ dev: !st.dev })),
    runDemo,
    runCustom,
    rerun,
    resubmit,
    toggleTrace: () => patch((st) => ({ traceOpen: !st.traceOpen })),
    onCustFiles,
    removeCustDoc,
    onPolicyFile,
    runEval,
  };
}

export type Engine = ReturnType<typeof useClaimEngine>;
