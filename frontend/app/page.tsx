"use client";

import { useClaimEngine } from "@/lib/engine";
import { TopBar } from "@/components/TopBar";
import { DemoView } from "@/components/DemoView";
import { CustomView } from "@/components/CustomView";
import { EvalView } from "@/components/EvalView";
import { ResultPanel } from "@/components/ResultPanel";
import { RunHistory } from "@/components/RunHistory";
import { Toast } from "@/components/Toast";

export default function Page() {
  const engine = useClaimEngine();
  const { state } = engine;
  const adjudicating = state.view !== "eval" && state.running;
  const showResult = state.view !== "eval" && state.hasDecision && !!state.decision;
  const showHistory = state.view !== "eval";

  return (
    <main className="shell">
      <div className="container">
        <TopBar engine={engine} />

        {state.view === "demo" && <DemoView engine={engine} />}
        {state.view === "custom" && <CustomView engine={engine} />}
        {state.view === "eval" && <EvalView engine={engine} />}

        {adjudicating && (
          <div
            className="card rise"
            style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 14 }}
          >
            <span className="spinner" />
            <div className="col" style={{ gap: 2 }}>
              <span style={{ fontWeight: 600, fontSize: 15, color: "var(--ink)" }}>
                Agents adjudicating…
              </span>
              <span style={{ fontSize: 13, color: "var(--muted)" }}>
                Running the agent graph against the policy.
              </span>
            </div>
          </div>
        )}

        {showResult && <ResultPanel engine={engine} />}
        {showHistory && <RunHistory engine={engine} />}
      </div>

      <Toast engine={engine} />
    </main>
  );
}
