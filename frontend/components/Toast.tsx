"use client";

import type { EngineProps } from "./ui";
import { STATUS_COLORS } from "./ui";

const TITLE: Record<string, string> = {
  APPROVED: "Approved 🎉",
  PARTIAL: "Partially approved",
  REJECTED: "Rejected",
  MANUAL_REVIEW: "Sent to manual review",
  BLOCKED: "Blocked — action needed",
};

export function Toast({ engine }: EngineProps) {
  const { toast } = engine.state;
  if (!toast) return null;
  return (
    <div className="toast">
      <div className="toast-inner">
        <span
          style={{
            flex: "none",
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: STATUS_COLORS[toast.status],
          }}
        />
        <span className="col" style={{ gap: 2 }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: "var(--on-ink)" }}>
            {TITLE[toast.status] || toast.status}
          </span>
          <span style={{ fontWeight: 500, fontSize: 12, color: "var(--on-ink-soft)" }}>
            {toast.sub}
          </span>
        </span>
      </div>
    </div>
  );
}
