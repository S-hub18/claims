"use client";

import type { EngineProps } from "./ui";
import type { View } from "@/lib/types";

const TABS: { id: View; label: string }[] = [
  { id: "demo", label: "Demo profiles" },
  { id: "custom", label: "Custom claim" },
  { id: "eval", label: "Eval suite" },
];

export function TopBar({ engine }: EngineProps) {
  const { state, setView, toggleDev } = engine;
  return (
    <div className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <span />
        </div>
        <span className="brand-name">ClaimAdjudication</span>
        <span className="brand-tag">multi-agent demo</span>
      </div>

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={state.view === t.id}
            className={`tab${state.view === t.id ? " active" : ""}`}
            onClick={() => setView(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="dev-switch">
        <span>Developer mode</span>
        <button
          className={`toggle${state.dev ? " on" : ""}`}
          aria-label="Toggle developer mode"
          aria-pressed={state.dev}
          onClick={toggleDev}
        >
          <span className="knob" />
        </button>
      </div>
    </div>
  );
}
