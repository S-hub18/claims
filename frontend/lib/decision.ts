import { fmt, confBand } from "./format";
import { catKeyFor } from "./policy";
import type {
  Decision,
  Policy,
  RunPlan,
  Scenario,
  Status,
  TraceFact,
  WaterfallRow,
} from "./types";

export interface DecisionCtx {
  amount: number;
  treatment: string;
  enrolled: number;
  subLimitScope: "covered" | "billed";
  confThreshold: number;
  disabled: Record<string, boolean>;
  policyVersion: string;
}

const wf = (
  label: string,
  val: string,
  opt: Partial<WaterfallRow> = {}
): WaterfallRow => ({ label, val, neg: opt.neg, muted: opt.muted, final: opt.final });

// ---- Demo (scenario-driven) decision ----
export function computeDecision(scenario: Scenario, ctx: DecisionCtx): Decision {
  const F = fmt;
  let status: Status = "APPROVED";
  let kind: Decision["kind"] = "financial";
  let message = "";
  let conf: number | null = 0.9;
  let lines: Decision["lines"] = [];
  let waterfall: WaterfallRow[] = [];
  let issues: Decision["issues"] = [];
  let reasons: string[] = [];
  let notes: string[] = [];
  let approved: number | null = 0;
  let claimed = ctx.amount;
  const cat = ctx.treatment;

  if (scenario === "approved") {
    conf = 0.94;
    const gross = ctx.amount;
    const disc = Math.round(gross * 0.2);
    const afterD = gross - disc;
    const copay = Math.round(afterD * 0.1);
    approved = afterD - copay;
    status = "APPROVED";
    claimed = gross;
    message = "Your " + cat + " claim is approved. Here’s exactly how we reached the payout.";
    lines = [{ label: cat + " services", amount: F(gross), tag: "covered", ref: "" }];
    waterfall = [
      wf("Gross covered", F(gross)),
      wf("Network discount · 20%", "−" + F(disc), { neg: true }),
      wf("Co-pay · 10%", "−" + F(copay), { neg: true }),
      wf("Sub-limit cap · ₹10,000", "not binding", { muted: true }),
      wf("Approved", F(approved), { final: true }),
    ];
  } else if (scenario === "exclusion") {
    conf = 0.92;
    const covered = 8000;
    const excluded = 4000;
    approved = covered;
    claimed = covered + excluded;
    status = "PARTIAL";
    message = "Root canal is covered in full. Teeth whitening is a cosmetic exclusion, so it isn’t paid.";
    lines = [
      { label: "Root canal", amount: F(covered), tag: "covered", ref: "" },
      { label: "Teeth whitening", amount: F(excluded), tag: "excluded", ref: "opd_categories.dental.excluded_procedures[1]" },
    ];
    waterfall = [
      wf("Gross covered", F(covered)),
      wf("Network discount · 0%", "not applied", { muted: true }),
      wf("Co-pay · 0%", "not applied", { muted: true }),
      wf("Sub-limit cap · ₹10,000", "not binding", { muted: true }),
      wf("Approved", F(approved), { final: true }),
    ];
  } else if (scenario === "partial") {
    conf = 0.88;
    const gross = ctx.amount;
    const cap = 25000;
    let approvedAmt: number;
    let w: WaterfallRow[];
    if (ctx.subLimitScope === "billed") {
      const capped = Math.min(gross, cap);
      const copay = Math.round(capped * 0.1);
      approvedAmt = capped - copay;
      w = [
        wf("Gross billed", F(gross)),
        wf("Sub-limit cap · ₹25,000", "→ " + F(capped), { neg: true }),
        wf("Co-pay · 10%", "−" + F(copay), { neg: true }),
        wf("Approved", F(approvedAmt), { final: true }),
      ];
    } else {
      const copay = Math.round(gross * 0.1);
      const afterC = gross - copay;
      approvedAmt = Math.min(afterC, cap);
      w = [
        wf("Gross covered", F(gross)),
        wf("Co-pay · 10%", "−" + F(copay), { neg: true }),
        wf("Sub-limit cap · ₹25,000", "→ " + F(approvedAmt), { neg: true }),
        wf("Approved", F(approvedAmt), { final: true }),
      ];
    }
    approved = approvedAmt;
    claimed = gross;
    status = "PARTIAL";
    message = "Your claim is valid, but the " + cat + " sub-limit caps the payout. Scope = " + ctx.subLimitScope + ".";
    lines = [{ label: cat + " services", amount: F(gross), tag: "covered", ref: "" }];
    waterfall = w;
  } else if (scenario === "blocked") {
    kind = "blocked";
    status = "BLOCKED";
    conf = null;
    approved = null;
    claimed = ctx.amount;
    message = "We checked everything in one pass. Sort these and resubmit once — no back-and-forth.";
    issues = [
      { n: 1, title: "Missing diagnostic report", detail: "Lab values are billed but no diagnostic report is attached. Add the lab report." },
      { n: 2, title: "Prescription date unreadable", detail: "Page 1’s date field didn’t read. Re-scan it clearly." },
      { n: 3, title: "Name mismatch on the bill", detail: "Bill says “R. Kumar”, policy says the full name. Confirm or correct it." },
    ];
  } else if (scenario === "manual") {
    kind = "manual";
    status = "MANUAL_REVIEW";
    conf = 0.62;
    approved = 32000;
    claimed = ctx.amount;
    message = "We’ve drafted a payout, but extraction confidence is too low to auto-approve. A reviewer will confirm.";
    lines = [{ label: cat + " services", amount: F(ctx.amount), tag: "covered", ref: "" }];
    waterfall = [wf("Gross covered", F(ctx.amount)), wf("Provisional approved", F(32000), { final: true })];
    reasons = ["Extraction confidence 0.62 is below the 0.70 floor.", "Discharge summary pages 2–3 are partially unreadable."];
    notes = ["Provisional only — not a final decision until a human confirms."];
  } else if (scenario === "rejectPerClaim") {
    kind = "reasons";
    status = "REJECTED";
    conf = 1.0;
    approved = 0;
    claimed = ctx.amount;
    message = "This claim exceeds the per-claim limit, so it’s rejected before any extraction runs.";
    reasons = ["Claimed " + F(ctx.amount) + " exceeds the per-claim limit of ₹1,00,000.", "PerClaimLimitAgent fired at t≈0 — no documents needed."];
  } else if (scenario === "rejectVelocity") {
    kind = "reasons";
    status = "REJECTED";
    conf = 1.0;
    approved = 0;
    claimed = ctx.amount;
    message = "Velocity fraud guard tripped — too many claims from this member in 24 hours.";
    reasons = ["5 claims submitted in the last 24h (limit 3).", "VelocityFraudAgent fired instantly off the claims ledger."];
  } else if (scenario === "rejectWaiting") {
    kind = "reasons";
    status = "REJECTED";
    conf = 0.93;
    approved = 0;
    claimed = ctx.amount;
    message = "This treatment falls inside the policy waiting period, so it can’t be paid yet.";
    reasons = ["Treatment date is within the " + cat + " waiting period.", "Member enrolled only " + (ctx.enrolled || 4) + " months ago."];
  } else if (scenario === "rejectPreAuth") {
    kind = "reasons";
    status = "REJECTED";
    conf = 0.9;
    approved = 0;
    claimed = ctx.amount;
    message = "Pre-authorisation is mandatory for this treatment and wasn’t obtained.";
    reasons = ["No pre-authorisation reference found in the documents.", "PreAuthAgent fired because " + cat + " is a diagnostic category."];
  }

  const dis = Object.keys(ctx.disabled || {});
  if (dis.length && conf != null && status !== "BLOCKED" && status !== "REJECTED") {
    conf = Math.max(0.4, conf - 0.08 * dis.length);
    dis.forEach((a) => notes.push(a + "Agent disabled — its verdict is treated as a degraded fact; confidence lowered."));
  }
  if (conf != null && (status === "APPROVED" || status === "PARTIAL") && conf < ctx.confThreshold) {
    notes.push("Extraction confidence " + conf.toFixed(2) + " is below your threshold " + ctx.confThreshold.toFixed(2) + " — escalated to manual review.");
    status = "MANUAL_REVIEW";
    kind = "manual";
    reasons = ["Confidence " + conf.toFixed(2) + " < threshold " + ctx.confThreshold.toFixed(2) + ".", ...reasons];
  }
  if (ctx.policyVersion && ctx.policyVersion !== "v9") {
    notes.push("Adjudicated on policy " + ctx.policyVersion + " — limits differ slightly from the current v9.");
  }

  return { status, kind, message, conf, confBand: confBand(conf), approved, claimed, lines, waterfall, issues, reasons, notes, category: cat };
}

export interface CustomState {
  custTreatment: string;
  custAmount: number;
  custHospital: string;
  confThreshold: number;
}

// ---- Custom (policy-driven) decision ----
export function computeCustomDecision(
  s: CustomState,
  policy: Policy
): { dec: Decision; scenario: Scenario } {
  const F = fmt;
  const label = s.custTreatment;
  const key = catKeyFor(label);
  const cat = key && policy.opd_categories ? policy.opd_categories[key] : null;
  const perClaim = (policy.coverage && policy.coverage.per_claim_limit) || 5000;
  const minAmt = (policy.submission_rules && policy.submission_rules.minimum_claim_amount) || 0;
  const autoManual = (policy.fraud_thresholds && policy.fraud_thresholds.auto_manual_review_above) || Infinity;
  const hospitals = policy.network_hospitals || [];
  const inNetwork = hospitals.indexOf(s.custHospital) >= 0;
  const discountPct = inNetwork ? (cat && cat.network_discount_percent) || 0 : 0;
  const copayPct = (cat && cat.copay_percent) || 0;
  const subLimit = cat && cat.sub_limit != null ? cat.sub_limit : null;
  const gross = s.custAmount;

  let status: Status = "APPROVED";
  let kind: Decision["kind"] = "financial";
  let message = "";
  let conf: number | null = 0.93;
  let lines: Decision["lines"] = [];
  let waterfall: WaterfallRow[] = [];
  let reasons: string[] = [];
  let notes: string[] = [];
  let approved: number | null = 0;
  const issues: Decision["issues"] = [];

  if (gross < minAmt) {
    kind = "reasons";
    status = "REJECTED";
    conf = 1.0;
    approved = 0;
    message = "Below the policy minimum claim amount, so it can’t be processed.";
    reasons = ["Claimed " + F(gross) + " is under the " + F(minAmt) + " minimum (submission_rules.minimum_claim_amount)."];
  } else if (gross > perClaim) {
    kind = "reasons";
    status = "REJECTED";
    conf = 1.0;
    approved = 0;
    message = "This claim exceeds the policy per-claim limit, so it’s rejected before extraction even runs.";
    reasons = [
      "Claimed " + F(gross) + " exceeds the per-claim limit of " + F(perClaim) + " (coverage.per_claim_limit).",
      "PerClaimLimitAgent fired at t≈0 — no documents needed.",
    ];
  } else {
    const covered = gross;
    const disc = Math.round(covered * discountPct / 100);
    const afterD = covered - disc;
    const copay = Math.round(afterD * copayPct / 100);
    const afterC = afterD - copay;
    const capBinds = subLimit != null && afterC > subLimit;
    approved = subLimit != null ? Math.min(afterC, subLimit) : afterC;
    lines = [{ label: label + " services", amount: F(gross), tag: "covered", ref: key ? "opd_categories." + key : "" }];
    waterfall = [wf("Gross covered", F(covered))];
    waterfall.push(
      discountPct > 0
        ? wf("Network discount · " + discountPct + "%", "−" + F(disc), { neg: true })
        : wf("Network discount", inNetwork ? "0% for " + label : "out-of-network — none", { muted: true })
    );
    waterfall.push(
      copayPct > 0
        ? wf("Co-pay · " + copayPct + "%", "−" + F(copay), { neg: true })
        : wf("Co-pay · 0%", "not applied", { muted: true })
    );
    if (subLimit != null) {
      waterfall.push(
        capBinds
          ? wf("Sub-limit cap · " + F(subLimit), "→ " + F(approved), { neg: true })
          : wf("Sub-limit cap · " + F(subLimit), "not binding", { muted: true })
      );
    }
    waterfall.push(wf("Approved", F(approved), { final: true }));
    if (!cat && key === null) {
      notes.push(label + " has no OPD sub-limit in this policy — bounded only by the per-claim limit.");
    }
    if (gross >= autoManual) {
      status = "MANUAL_REVIEW";
      kind = "manual";
      conf = 0.7;
      message = "Drafted a payout, but this is a high-value claim and needs a human reviewer first.";
      reasons = ["Claim ≥ " + F(autoManual) + " (fraud_thresholds.auto_manual_review_above) — auto manual review."];
      notes.push("High-value claim flagged before payout.");
    } else {
      status = capBinds ? "PARTIAL" : "APPROVED";
      message = capBinds
        ? "Valid claim, but the " + label + " sub-limit of " + F(subLimit) + " caps the payout."
        : "Approved under " + (policy.policy_name || "the policy") + ". Every deduction follows the policy you uploaded.";
    }
  }

  if (conf != null && (status === "APPROVED" || status === "PARTIAL") && conf < s.confThreshold) {
    notes.push("Confidence " + conf.toFixed(2) + " is below your threshold " + s.confThreshold.toFixed(2) + " — escalated to manual review.");
    status = "MANUAL_REVIEW";
    kind = "manual";
    reasons = ["Confidence " + conf.toFixed(2) + " < threshold " + s.confThreshold.toFixed(2) + ".", ...reasons];
  }

  const dec: Decision = {
    status,
    kind,
    message,
    conf,
    confBand: confBand(conf),
    approved,
    claimed: gross,
    lines,
    waterfall,
    issues,
    reasons,
    notes,
    category: label,
  };
  const scenario: Scenario =
    status === "REJECTED" ? "rejectPerClaim" : status === "MANUAL_REVIEW" ? "manual" : status === "PARTIAL" ? "partial" : "approved";
  return { dec, scenario };
}

// ---- Trace facts (board removed, but the trace stays accessible) ----
const AGENT_LABELS: Record<string, string> = {
  VelocityFraud: "VelocityFraud",
  PerClaimLimit: "PerClaimLimit",
  HighValue: "HighValueAgent",
  MemberResolver: "MemberResolver",
  DocDetector: "DocDetector",
  Extractor: "Extractor ×2",
  DocGate: "DocGate",
  SemanticMapper: "SemanticMapper",
  PatientResolver: "PatientResolver",
  FinancialReconciler: "FinancialRecon",
  ClinicalChain: "ClinicalChain",
  WaitingPeriod: "WaitingPeriod",
  Exclusion: "ExclusionAgent",
  PreAuth: "PreAuthAgent",
  AggregateLimits: "AggregateLimits",
  DocumentFraud: "DocFraudAgent",
  FinancialCalc: "FinancialCalc",
  DecisionAgg: "DecisionAgg",
  Verifier: "Verifier",
};

const TIMING: Record<string, number> = {
  VelocityFraud: 150, PerClaimLimit: 210, HighValue: 300, MemberResolver: 360, DocDetector: 560,
  Extractor: 1350, DocGate: 1650, SemanticMapper: 1780, PatientResolver: 1850, FinancialReconciler: 1950,
  ClinicalChain: 2080, WaitingPeriod: 2230, Exclusion: 2360, PreAuth: 2470, AggregateLimits: 2580,
  DocumentFraud: 2690, FinancialCalc: 2900, DecisionAgg: 3120, Verifier: 3360,
};

function keyMap(blocked: boolean): Record<string, string> {
  return {
    MemberResolver: "member", PerClaimLimit: "verdict.limits.per_claim", HighValue: "verdict.fraud.high_value",
    VelocityFraud: "verdict.fraud.velocity", DocDetector: "segment.*", Extractor: "extraction.{id}",
    DocGate: blocked ? "gate.blocked" : "gate.passed", SemanticMapper: "semantic_map", PatientResolver: "patient_identity",
    FinancialReconciler: "financial_facts", ClinicalChain: "clinical_chain", WaitingPeriod: "verdict.waiting_period",
    Exclusion: "verdict.exclusion", PreAuth: "verdict.pre_auth", AggregateLimits: "verdict.limits.aggregate",
    DocumentFraud: "verdict.fraud.document", FinancialCalc: "financial_breakdown", DecisionAgg: "decision", Verifier: "verifier_result",
  };
}

const DIAG = ["Diagnostics", "Hospitalization"];

// Builds the trace fact list + agent count for a decision, without animation.
export function computeRun(scenario: Scenario, ctx: DecisionCtx, dec: Decision): RunPlan {
  const blocked = dec.kind === "blocked";
  const diag = DIAG.includes(ctx.treatment);
  const skipWaiting = !blocked && ctx.enrolled >= 12 && scenario !== "rejectWaiting";
  const skipPreAuth = !blocked && !diag && scenario !== "rejectPreAuth";
  const dis = ctx.disabled || {};
  const verifierSkip = ["REJECTED", "BLOCKED", "MANUAL_REVIEW"].includes(dec.status);
  const KEY = keyMap(blocked);

  type Step = { id: string; st: string; key: string; conf: number | null; reason?: string; at: number; degraded?: boolean };
  const out: Record<string, Step> = {};
  Object.keys(TIMING).forEach((id) => {
    out[id] = { id, st: "posted", key: KEY[id], conf: 0.9, at: TIMING[id] };
  });
  out.MemberResolver.conf = 0.99;
  out.HighValue.conf = 1.0;
  out.PerClaimLimit.conf = 1.0;
  out.VelocityFraud.conf = 1.0;
  out.Extractor.conf = scenario === "manual" ? 0.62 : 0.93;
  out.PatientResolver.conf = 0.97;
  out.ClinicalChain.conf = 0.9;
  out.DecisionAgg.conf = dec.conf;

  const skip = (id: string, reason: string, degraded?: boolean) => {
    out[id] = { ...out[id], st: degraded ? "degraded" : "skipped", key: "skipped." + id, reason, conf: null, degraded };
  };
  if (skipWaiting) skip("WaitingPeriod", "PROVABLY_PASS");
  if (skipPreAuth) skip("PreAuth", "PROVABLY_PASS");
  if (verifierSkip) skip("Verifier", "GUARD_FIRED");
  if (blocked) {
    ["SemanticMapper", "PatientResolver", "FinancialReconciler", "ClinicalChain", "WaitingPeriod", "Exclusion", "PreAuth", "AggregateLimits", "DocumentFraud", "FinancialCalc", "Verifier"].forEach(
      (id) => skip(id, "GATE_BLOCKED")
    );
  }
  Object.keys(dis).forEach((id) => {
    if (out[id]) skip(id, "DISABLED", true);
  });

  let finalAt: number;
  if (blocked) {
    out.DocGate.at = 1650;
    out.DecisionAgg.at = 2000;
    out.DecisionAgg.conf = null;
    Object.values(out).forEach((o) => {
      if (o.reason === "GATE_BLOCKED") o.at = 1800;
    });
    finalAt = 2150;
  } else {
    finalAt = scenario === "rejectPerClaim" || scenario === "rejectVelocity" ? 3050 : 3520;
  }

  const order = Object.values(out).sort((a, b) => a.at - b.at);
  const facts: TraceFact[] = order.map((s, i) => ({
    seq: i + 1,
    key: s.key,
    author: AGENT_LABELS[s.id] || s.id,
    conf: s.conf,
    degraded: s.degraded,
    reason: s.reason,
  }));
  const agentsFired = order.filter((s) => s.st === "posted" || s.st === "degraded").length;

  return { decision: dec, facts, agentsFired, elapsedMs: finalAt };
}
