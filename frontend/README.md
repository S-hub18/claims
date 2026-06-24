# Claimstream — frontend

Next.js (App Router + TypeScript) port of the `Claimstream.dc.html` demo: a multi-agent
health-insurance claims adjudication console with three views — **Demo profiles**,
**Custom claim**, and **Eval suite** — plus a shared run history.

## Run

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run build    # production build
```

## What changed from the reference demo

- **Removed the live animated board.** The reference opened a "decision panel" that animated the
  agent graph + fact stream live after you pressed *Run adjudication*. That panel is gone. Run now
  shows a brief `Agents adjudicating…` spinner and jumps straight to the **result panel**
  (status, line items, waterfall, payout side-card). The agent trace is still available behind
  *View full trace* in the result panel — it's just no longer animated.
- **Re-skinned to the Cursor design system** with **`#FF3F52`** as the single brand color:
  warm cream canvas (`#f7f7f4`), warm ink text (`#26251e`), hairline-only depth (no drop shadows),
  Inter for UI + JetBrains Mono for code/numeric surfaces, 8px CTA / 12px card radii. No purple.

## Structure

- `lib/` — framework-free domain layer: `types.ts`, `policy.ts`, `profiles.ts`, `testcases.ts`,
  `decision.ts` (the adjudication engine, ported from the reference `computeDecision` /
  `computeCustomDecision` / `computeRun`), `engine.ts` (`useClaimEngine` state hook).
- `components/` — `TopBar`, `DemoView`, `CustomView`, `EvalView`, `ResultPanel`, `RunHistory`,
  `PolicyPanel`, `DevConfig`, `Toast`, and shared `ui.tsx` primitives.
- `app/` — `layout.tsx` (fonts + global CSS), `page.tsx` (composition), `globals.css` (design tokens).

The adjudication logic runs entirely client-side (faithful to the reference simulation); no backend
calls are required to demo it.
