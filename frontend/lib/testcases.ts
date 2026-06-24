import type { TestCase } from "./types";

// Graded eval suite — each case asserts decision & payout against expectation.
export const TEST_CASES: TestCase[] = [
  { id: "TC001", title: "Missing diagnostic report", cat: "Diagnostics", expected: "BLOCKED", approved: null, conf: null, ms: 900 },
  { id: "TC002", title: "Wrong document type uploaded", cat: "Pharmacy", expected: "BLOCKED", approved: null, conf: null, ms: 820 },
  { id: "TC003", title: "Bill with no line items", cat: "Hospitalization", expected: "BLOCKED", approved: null, conf: null, ms: 1010 },
  { id: "TC004", title: "Clean OPD claim", cat: "OPD Consultation", expected: "APPROVED", approved: 4500, conf: 0.95, ms: 1700 },
  { id: "TC005", title: "Within waiting period", cat: "Dental", expected: "REJECTED", approved: 0, conf: 0.93, ms: 720 },
  { id: "TC006", title: "Teeth whitening excluded", cat: "Dental", expected: "APPROVED", approved: 8000, conf: 0.92, ms: 1600 },
  { id: "TC007", title: "Pre-auth not obtained", cat: "Hospitalization", expected: "REJECTED", approved: 0, conf: 0.9, ms: 1480 },
  { id: "TC008", title: "Per-claim limit exceeded", cat: "Vision", expected: "REJECTED", approved: 0, conf: 1.0, ms: 300 },
  { id: "TC009", title: "Velocity fraud · 5 claims/24h", cat: "Pharmacy", expected: "REJECTED", approved: 0, conf: 1.0, ms: 320 },
  { id: "TC010", title: "Network discount + co-pay", cat: "OPD Consultation", expected: "APPROVED", approved: 3240, conf: 0.94, ms: 1750 },
  {
    id: "TC011",
    title: "Low-confidence scan · degraded",
    cat: "Pharmacy",
    expected: "APPROVED",
    approved: 4000,
    conf: 0.68,
    ms: 1900,
    note: "Decided with a manual-review note — confidence 0.68, below comfort but above floor.",
  },
  { id: "TC012", title: "Exclusion precedence over limit", cat: "Dental", expected: "APPROVED", approved: 8000, conf: 0.91, ms: 1650 },
];
