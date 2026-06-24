// Small formatting + icon helpers shared across views.

export function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

export function iconFor(name: string): string {
  const n = (name || "").toLowerCase();
  if (n.match(/presc/)) return "📄";
  if (n.match(/lab|diag|report/)) return "🔬";
  if (n.match(/discharge|summary/)) return "📋";
  if (n.match(/bill|invoice|receipt/)) return "🧾";
  if (n.match(/\.pdf$/)) return "📄";
  if (n.match(/\.(png|jpe?g|webp|heic)$/)) return "🖼️";
  return "📎";
}

export function confBand(c: number | null): string {
  if (c == null) return "";
  if (c >= 0.9) return "high";
  if (c >= 0.78) return "good";
  if (c >= 0.7) return "moderate";
  return "low";
}

export function titleCase(k: string): string {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function filesToObjs(list: FileList | File[] | null) {
  return Array.from(list || []).map((f) => ({
    name: f.name,
    icon: iconFor(f.name),
    meta: (f.size ? Math.max(1, Math.round(f.size / 1024)) : 120) + " KB",
  }));
}

export function docToCat(d: string): string {
  const n = (d || "").toLowerCase();
  if (n.match(/discharge/)) return "Hospitalization";
  if (n.match(/lab/)) return "Diagnostics";
  if (n.match(/pharm/)) return "Pharmacy";
  if (n.match(/presc/)) return "OPD Consultation";
  return "OPD Consultation";
}
