// Domain types for the Claimstream adjudication UI.
// Mirrors the data shapes in the reference Claimstream.dc.html simulation.

export type Status =
  | "APPROVED"
  | "PARTIAL"
  | "REJECTED"
  | "MANUAL_REVIEW"
  | "BLOCKED";

export type DecisionKind = "financial" | "blocked" | "reasons" | "manual";

export type Scenario =
  | "approved"
  | "exclusion"
  | "partial"
  | "blocked"
  | "manual"
  | "rejectPerClaim"
  | "rejectVelocity"
  | "rejectWaiting"
  | "rejectPreAuth";

export type TreatmentType =
  | "Dental"
  | "Vision"
  | "OPD Consultation"
  | "Diagnostics"
  | "Pharmacy"
  | "Hospitalization";

export interface DocFile {
  name: string;
  icon: string;
  meta: string;
  yours?: boolean;
}

export interface LineItem {
  label: string;
  amount: string;
  tag: "covered" | "excluded";
  ref?: string;
}

export interface WaterfallRow {
  label: string;
  val: string;
  neg?: boolean;
  muted?: boolean;
  final?: boolean;
}

export interface BlockIssue {
  n: number;
  title: string;
  detail: string;
}

export interface Decision {
  status: Status;
  kind: DecisionKind;
  message: string;
  conf: number | null;
  confBand: string;
  approved: number | null;
  claimed: number;
  lines: LineItem[];
  waterfall: WaterfallRow[];
  issues: BlockIssue[];
  reasons: string[];
  notes: string[];
  category: string;
  claimId?: string;
}

export interface TraceFact {
  seq: number;
  key: string;
  author: string;
  conf: number | null;
  degraded?: boolean;
  reason?: string;
  // The agent's posted value (verdict object, extraction dict, …) and the fact keys
  // it was derived from. The lifecycle/eval view reads these to render each step in
  // plain English and surface every issue a check raised. ``tMs`` is the cumulative
  // milliseconds from claim creation to when this step landed (per-step timing).
  value?: unknown;
  derivedFrom?: string[];
  tMs?: number;
}

export interface RunPlan {
  decision: Decision;
  facts: TraceFact[];
  agentsFired: number;
  elapsedMs: number;
}

export interface HistoryRow {
  claimId: string;
  member: string;
  category: string;
  status: Status;
  approved: string;
  conf: string;
  time: string;
}

export interface Profile {
  id: string;
  name: string;
  initials: string;
  color: string;
  memberId: string;
  policy: string;
  enrolled: number;
  treatment: TreatmentType;
  amount: number;
  scenario: Scenario;
  badge: string;
  docs: DocFile[];
}

export interface TestCase {
  id: string;
  title: string;
  cat: string;
  expected: Status;
  approved: number | null;
  conf: number | null;
  ms: number;
  note?: string | null;
  custom?: boolean;
}

export interface EvalResult {
  running?: boolean;
  done?: boolean;
  actual?: Status;
  pass?: boolean;
  approved?: number | null;
  conf?: number | null;
  ms?: number;
  note?: string | null;
}

export interface Policy {
  policy_id: string;
  policy_name: string;
  insurer: string;
  coverage: {
    sum_insured_per_employee: number;
    annual_opd_limit: number;
    per_claim_limit: number;
  };
  opd_categories: Record<string, PolicyCategory>;
  waiting_periods: Record<string, number>;
  fraud_thresholds: {
    same_day_claims_limit: number;
    monthly_claims_limit: number;
    high_value_claim_threshold: number;
    auto_manual_review_above: number;
  };
  network_hospitals: string[];
  submission_rules: {
    deadline_days_from_treatment: number;
    minimum_claim_amount: number;
    currency: string;
  };
}

export interface PolicyCategory {
  sub_limit?: number;
  copay_percent?: number;
  network_discount_percent?: number;
  requires_pre_auth?: boolean;
  branded_drug_copay_percent?: number;
  excluded_procedures?: string[];
  excluded_items?: string[];
  high_value_tests_requiring_pre_auth?: string[];
  max_sessions_per_year?: number;
}

export type View = "demo" | "custom" | "eval";
