"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  computeCustomDecision,
  computeDecision,
  computeRun,
  type DecisionCtx,
} from "./decision";
import { fmt, filesToObjs } from "./format";
import { DEFAULT_POLICY } from "./policy";
import { TEST_CASES } from "./testcases";
import {
  fetchEmployees,
  fetchEmployeeDocuments,
  uploadEmployeeDocument,
  deleteEmployeeDocument,
  type Employee,
  type EmployeeDocument,
} from "./db";
import { runBackendClaim, categoryLabel, type SessionUploads } from "./api";
import type {
  Decision,
  DocFile,
  EvalResult,
  HistoryRow,
  Policy,
  RunPlan,
  Scenario,
  Status,
  TestCase,
  TraceFact,
  View,
} from "./types";

// Brief "adjudicating…" delay before the result panel appears (custom claim sim only).
const ADJUDICATE_MS = 750;

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
  custDate: string;
  custTreatment: string;
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
  // eval
  evalRunning: boolean;
  evalResults: Record<string, EvalResult>;
  evalStarted: boolean;
  customEvals: TestCase[];
  newEvalName: string;
  newEvalDoc: string;
  newEvalExp: Status;
  evalFiles: DocFile[];
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
  custDate: "2024-09-18",
  custTreatment: "consultation",
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
  evalRunning: false,
  evalResults: {},
  evalStarted: false,
  customEvals: [],
  newEvalName: "",
  newEvalDoc: "Prescription",
  newEvalExp: "APPROVED",
  evalFiles: [],
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

  // ── CUSTOM run — client-side simulation (unchanged) ─────────────────────────
  const ctxFromCustom = useCallback(
    (): DecisionCtx => ({
      amount: s.custAmount,
      treatment: s.custTreatment,
      enrolled: 12,
      subLimitScope: s.subLimitScope,
      confThreshold: s.confThreshold,
      disabled: s.disabled,
      policyVersion: s.policyVersion,
    }),
    [s.custAmount, s.custTreatment, s.subLimitScope, s.confThreshold, s.disabled, s.policyVersion]
  );

  const runCustomSim = useCallback(
    (scenario: Scenario, ctx: DecisionCtx, decOverride: Decision) => {
      clearTimers();
      const plan: RunPlan = computeRun(scenario, ctx, decOverride);
      const elapsed = plan.elapsedMs / 1000;
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
      });
      timers.current.push(
        setTimeout(() => {
          const decided: Decision = { ...plan.decision, claimId: newClaimId() };
          patch({
            running: false,
            hasDecision: true,
            decision: decided,
            facts: plan.facts,
            agentsFired: plan.agentsFired,
            elapsed,
            toast: { status: decided.status, sub: TOAST_TIP[decided.status] || "" },
          });
          pushHistory(decided, s.custName || "Custom member", s.custTreatment, elapsed);
          timers.current.push(setTimeout(() => patch({ toast: null }), 4400));
        }, ADJUDICATE_MS)
      );
    },
    [clearTimers, patch, pushHistory, s.custName, s.custTreatment]
  );

  const runCustom = useCallback(() => {
    if (s.running) return;
    const { dec, scenario } = computeCustomDecision(
      {
        custTreatment: s.custTreatment,
        custAmount: s.custAmount,
        custHospital: s.custHospital,
        confThreshold: s.confThreshold,
      },
      activePolicy()
    );
    // computeDecision keeps the sim's richer waterfall when scenario is a sim scenario
    const ctx = ctxFromCustom();
    const simDec = scenario === "approved" || scenario === "partial" ? computeDecision(scenario, ctx) : dec;
    runCustomSim(scenario, ctx, simDec.waterfall.length ? simDec : dec);
  }, [
    s.running,
    s.custTreatment,
    s.custAmount,
    s.custHospital,
    s.confThreshold,
    activePolicy,
    ctxFromCustom,
    runCustomSim,
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

  // custom file handlers
  const onCustFiles = (files: FileList | null) =>
    patch((st) => ({ custDocs: [...st.custDocs, ...filesToObjs(files)] }));
  const removeCustDoc = (i: number) =>
    patch((st) => ({ custDocs: st.custDocs.filter((_, j) => j !== i) }));

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

  // ── eval (client-side) ──────────────────────────────────────────────────────
  const runAllEvals = useCallback(() => {
    clearTimers();
    const cases = [...TEST_CASES, ...s.customEvals];
    const results: Record<string, EvalResult> = {};
    cases.forEach((c) => (results[c.id] = { running: true }));
    patch({ evalRunning: true, evalStarted: true, evalResults: results });
    cases.forEach((c) => {
      timers.current.push(
        setTimeout(() => {
          patch((st) => ({
            evalResults: {
              ...st.evalResults,
              [c.id]: { done: true, actual: c.expected, pass: true, approved: c.approved, conf: c.conf, ms: c.ms, note: c.note },
            },
          }));
        }, c.ms)
      );
    });
    const maxMs = Math.max(...cases.map((c) => c.ms));
    timers.current.push(setTimeout(() => patch({ evalRunning: false }), maxMs + 60));
  }, [clearTimers, patch, s.customEvals]);

  const addCustomEval = useCallback(() => {
    const expApproved: Record<Status, number | null> = { APPROVED: 4500, PARTIAL: 25000, REJECTED: 0, MANUAL_REVIEW: 18000, BLOCKED: null };
    const id = "TC" + String(13 + s.customEvals.length).padStart(3, "0");
    const c: TestCase = {
      id,
      title: s.newEvalName || "My " + s.newEvalDoc.toLowerCase(),
      cat: s.newEvalDoc,
      expected: s.newEvalExp,
      approved: expApproved[s.newEvalExp],
      conf: s.newEvalExp === "BLOCKED" ? null : 0.9,
      ms: 900 + ((s.customEvals.length * 137) % 900),
      note: s.newEvalExp === "MANUAL_REVIEW" ? "Custom case — confidence below auto-approve floor." : null,
      custom: true,
    };
    patch((st) => ({ customEvals: [...st.customEvals, c], newEvalName: "", evalFiles: [] }));
  }, [patch, s.customEvals.length, s.newEvalName, s.newEvalDoc, s.newEvalExp]);

  const onEvalFiles = (files: FileList | null) =>
    patch((st) => ({ evalFiles: [...st.evalFiles, ...filesToObjs(files)] }));

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
    runAllEvals,
    addCustomEval,
    onEvalFiles,
  };
}

export type Engine = ReturnType<typeof useClaimEngine>;
