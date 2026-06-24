"use client";

import type { CSSProperties, ReactNode } from "react";
import type { Engine } from "@/lib/engine";
import type { Status } from "@/lib/types";

export interface EngineProps {
  engine: Engine;
}

// Status → brand-consistent semantic color (CSS custom properties from globals.css).
export const STATUS_COLORS: Record<Status, string> = {
  APPROVED: "var(--st-approved)",
  PARTIAL: "var(--st-partial)",
  REJECTED: "var(--st-rejected)",
  MANUAL_REVIEW: "var(--st-manual)",
  BLOCKED: "var(--st-blocked)",
};

export function statusLabel(s: Status): string {
  return s.replace("_", " ");
}

export function StatusPill({ status, style }: { status: Status; style?: CSSProperties }) {
  return (
    <span className="pill status-pill" style={{ background: STATUS_COLORS[status], ...style }}>
      {statusLabel(status)}
    </span>
  );
}

export function SectionLabel({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="section-label" style={{ margin: "20px 0 10px", ...style }}>
      {children}
    </div>
  );
}

export function Select({
  value,
  onChange,
  children,
  style,
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div className="select-wrap" style={style}>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
      <span className="select-caret">▾</span>
    </div>
  );
}
