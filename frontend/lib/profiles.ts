import type { Profile } from "./types";

const PDF = "📄";
const BILL = "🧾";

// Pre-built demo members, each mapping to a distinct adjudication path.
export const PROFILES: Profile[] = [
  {
    id: "priya",
    name: "Priya Menon",
    initials: "PM",
    color: "#1f8a65",
    memberId: "MEM-2088",
    policy: "PLM-GRP-77",
    enrolled: 8,
    treatment: "OPD Consultation",
    amount: 4500,
    scenario: "approved",
    badge: "Clean approval",
    docs: [
      { name: "consult_note.pdf", icon: PDF, meta: "1 page · 120 KB" },
      { name: "opd_bill.jpg", icon: BILL, meta: "1 page · 96 KB" },
    ],
  },
  {
    id: "rajesh",
    name: "Rajesh Kumar",
    initials: "RK",
    color: "#b45f06",
    memberId: "MEM-1042",
    policy: "PLM-GRP-77",
    enrolled: 14,
    treatment: "Dental",
    amount: 12000,
    scenario: "exclusion",
    badge: "Partial · exclusion",
    docs: [
      { name: "prescription.pdf", icon: PDF, meta: "2 pages · 240 KB" },
      { name: "dental_bill.jpg", icon: BILL, meta: "1 page · 180 KB" },
    ],
  },
  {
    id: "ananya",
    name: "Ananya Singh",
    initials: "AS",
    color: "#FF3F52",
    memberId: "MEM-3120",
    policy: "PLM-GRP-90",
    enrolled: 9,
    treatment: "Pharmacy",
    amount: 60000,
    scenario: "partial",
    badge: "Partial · sub-limit",
    docs: [
      { name: "prescription.pdf", icon: PDF, meta: "2 pages · 210 KB" },
      { name: "pharmacy_invoice.pdf", icon: BILL, meta: "1 page · 140 KB" },
    ],
  },
  {
    id: "dev",
    name: "Dev Varma",
    initials: "DV",
    color: "#475569",
    memberId: "MEM-4501",
    policy: "PLM-GRP-77",
    enrolled: 19,
    treatment: "Diagnostics",
    amount: 7000,
    scenario: "blocked",
    badge: "Blocked · gate",
    docs: [{ name: "lab_bill.jpg", icon: BILL, meta: "1 page · 150 KB" }],
  },
  {
    id: "meera",
    name: "Meera Iyer",
    initials: "MI",
    color: "#6b6256",
    memberId: "MEM-5077",
    policy: "PLM-GRP-90",
    enrolled: 5,
    treatment: "Hospitalization",
    amount: 48000,
    scenario: "manual",
    badge: "Manual review",
    docs: [
      { name: "discharge_summary.pdf", icon: PDF, meta: "3 pages · 380 KB" },
      { name: "hospital_bill.pdf", icon: BILL, meta: "2 pages · 260 KB" },
    ],
  },
];

export const TREATMENTS = [
  "Dental",
  "Vision",
  "OPD Consultation",
  "Diagnostics",
  "Pharmacy",
  "Hospitalization",
] as const;
