"use client";

import { useEffect, useRef, useState } from "react";

// Render a PDF with PDF.js onto <canvas> elements — one per page, drawn exactly
// once. This sidesteps the browser's native PDF plugin (<iframe> can come up
// blank, <object>/<embed> double-render in WebKit), giving identical output
// everywhere. The worker is loaded from a CDN pinned to the installed version.
//
// React StrictMode runs effects twice in dev; without a guard, both runs append
// canvases and you get "each page twice". A monotonic render token in a ref —
// shared mutable state, not a stale closure boolean — ensures only the latest
// run may ever touch the DOM, so pages render exactly once.
export function PdfCanvas({ url, fileName }: { url: string; fileName: string }) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const runSeq = useRef(0);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const myRun = ++runSeq.current;
    const stale = () => myRun !== runSeq.current;
    host.replaceChildren();
    setStatus("loading");

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        if (stale()) return;
        pdfjs.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.mjs`;

        const doc = await pdfjs.getDocument({ url }).promise;
        if (stale()) return;

        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const cssWidth = Math.min(host.clientWidth || 560, 560);

        for (let n = 1; n <= doc.numPages; n++) {
          const page = await doc.getPage(n);
          if (stale()) return;
          const base = page.getViewport({ scale: 1 });
          const scale = cssWidth / base.width;
          const viewport = page.getViewport({ scale: scale * dpr });

          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = "100%";
          canvas.style.display = "block";
          canvas.style.borderRadius = "var(--r-md)";
          canvas.style.border = "1px solid var(--hairline)";
          if (n > 1) canvas.style.marginTop = "12px";

          const ctx = canvas.getContext("2d");
          if (!ctx) continue;
          await page.render({ canvasContext: ctx, viewport }).promise;
          // Re-check AFTER render: a newer run may have started meanwhile, and a
          // newer run also clears the host — so only append if still current.
          if (stale()) return;
          host.appendChild(canvas);
        }
        if (!stale()) setStatus("ready");
      } catch {
        if (!stale()) setStatus("error");
      }
    })();

    return () => {
      // Bump the token so any in-flight run sees itself as stale and stops.
      runSeq.current++;
    };
  }, [url]);

  return (
    <div className="col" style={{ gap: 10 }}>
      <div
        ref={hostRef}
        style={{
          minHeight: status === "loading" ? 120 : undefined,
          position: "relative",
        }}
      />
      {status === "loading" && (
        <div className="row center" style={{ gap: 10, padding: "8px 0" }}>
          <span className="spinner" />
          <span style={{ fontSize: 13, color: "var(--muted)" }}>Rendering {fileName}…</span>
        </div>
      )}
      {status === "error" && (
        <div style={{ fontSize: 13.5, color: "var(--muted)" }}>
          Couldn’t render inline — use the button below to open the PDF.
        </div>
      )}
      <a
        className="btn btn-secondary"
        href={url}
        target="_blank"
        rel="noreferrer"
        style={{ alignSelf: "flex-start" }}
      >
        Open original PDF in new tab ↗
      </a>
    </div>
  );
}
