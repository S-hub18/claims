import type { Policy, TreatmentType } from "./types";

// Default sample policy — mirrors policy_terms.json from the reference demo.
export const DEFAULT_POLICY: Policy = {
  policy_id: "PLUM_GHI_2024",
  policy_name: "Group Health Insurance — Standard Plan",
  insurer: "ICICI Lombard General Insurance",
  coverage: {
    sum_insured_per_employee: 500000,
    annual_opd_limit: 50000,
    per_claim_limit: 5000,
  },
  opd_categories: {
    consultation: {
      sub_limit: 2000,
      copay_percent: 10,
      network_discount_percent: 20,
      requires_pre_auth: false,
    },
    diagnostic: {
      sub_limit: 10000,
      copay_percent: 0,
      network_discount_percent: 10,
      requires_pre_auth: true,
      high_value_tests_requiring_pre_auth: ["MRI", "CT Scan", "PET Scan"],
    },
    pharmacy: { sub_limit: 15000, copay_percent: 0, branded_drug_copay_percent: 30 },
    dental: {
      sub_limit: 10000,
      copay_percent: 0,
      excluded_procedures: [
        "Teeth Whitening",
        "Veneers",
        "Orthodontic Treatment (Braces)",
        "Implants (Cosmetic)",
        "Bleaching",
      ],
    },
    vision: {
      sub_limit: 5000,
      copay_percent: 0,
      excluded_items: ["LASIK Surgery", "Cosmetic Eye Surgery", "Refractive Surgery"],
    },
    alternative_medicine: { sub_limit: 8000, copay_percent: 0, max_sessions_per_year: 20 },
  },
  waiting_periods: { initial_waiting_period_days: 30, pre_existing_conditions_days: 365 },
  fraud_thresholds: {
    same_day_claims_limit: 2,
    monthly_claims_limit: 6,
    high_value_claim_threshold: 25000,
    auto_manual_review_above: 25000,
  },
  network_hospitals: [
    "Apollo Hospitals",
    "Fortis Healthcare",
    "Max Healthcare",
    "Manipal Hospitals",
    "Narayana Health",
    "Medanta",
    "Kokilaben Dhirubhai Ambani Hospital",
    "Aster CMI Hospital",
    "Columbia Asia",
    "Sakra World Hospital",
  ],
  submission_rules: {
    deadline_days_from_treatment: 30,
    minimum_claim_amount: 500,
    currency: "INR",
  },
};

export function catKeyFor(label: TreatmentType | string): string | null {
  const map: Record<string, string | null> = {
    "OPD Consultation": "consultation",
    Diagnostics: "diagnostic",
    Pharmacy: "pharmacy",
    Dental: "dental",
    Vision: "vision",
    Hospitalization: null,
  };
  return map[label] ?? null;
}
