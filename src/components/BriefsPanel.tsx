import { useCallback, useEffect, useState } from "react";
import { api, type Briefs } from "../lib/api";

const LABELS: Record<string, string> = {
  chat: "💬 Chat", plan: "🗂️ Plan", ideation: "💡 Ideation", research: "🔬 Research",
  orchestrator: "🧩 Orchestrator", advisor: "🧭 Advisor", docs: "📄 Docs",
};
const ORDER = ["chat", "plan", "ideation", "research", "orchestrator", "advisor", "docs"];

// "Overview" — the preliminary response for every feature in one place, kept current by chat.
export default function BriefsPanel({ projectId }: { projectId: number }) {
  const [briefs, setBriefs] = useState<Briefs>({});
  const [busy, setBusy] = useState(false);
  const [changed, setChanged] = useState<string[]>([]);

  const load = useCallback(async () => {
    try { setBriefs((await api.getBriefs(projectId)).briefs); } catch { /* offline */ }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    function onUpdate(e: Event) {
      const d = (e as CustomEvent).detail as { projectId: number; changed: string[] };
      if (d?.projectId !== projectId) return;
      void load();
      setChanged(d.changed ?? []);
      setTimeout(() => setChanged([]), 1800);
    }
    window.addEventListener("phorrom:briefs-updated", onUpdate);
    return () => window.removeEventListener("phorrom:briefs-updated", onUpdate);
  }, [projectId, load]);

  async function regenerate() {
    setBusy(true);
    try { setBriefs((await api.generateBriefs(projectId)).briefs); }
    finally { setBusy(false); }
  }

  return (
    <div className="advisor">
      <section>
        <h2>Overview — preliminary response per feature</h2>
        <p className="hint" style={{ textAlign: "left", marginBottom: 12 }}>
          Generated from your project description and kept current by the Chat tab. Each feature
          keeps only its top key points, ranked by importance (compressed, not stored verbatim).
        </p>
        <div className="task-add">
          <button onClick={() => void regenerate()} disabled={busy}>
            {busy ? "Regenerating…" : "Regenerate from project setup"}
          </button>
          <span className="hint">Chat updates these automatically — no need to regenerate manually.</span>
        </div>

        {ORDER.filter((k) => briefs[k]).map((k) => {
          const b = briefs[k];
          const pts = [...b.points].sort((a, c) => c.importance - a.importance);
          return (
            <div key={k} className={`bt-card ${changed.includes(k) ? "flash" : ""}`}
              style={{ flexDirection: "column", alignItems: "stretch" }}>
              <div className="bt-title">
                {LABELS[k] ?? k}
                {changed.includes(k) && <span className="bt-score">updated ✓</span>}
              </div>
              <p className="meta" style={{ fontSize: 13.5 }}>{b.summary}</p>
              {pts.length > 0 && (
                <ul className="brief-points" style={{ marginTop: 8 }}>
                  {pts.map((p, i) => (
                    <li key={i} title={`importance ${p.importance.toFixed(2)} · ${p.source}`}>
                      <span className="brief-bar" style={{ width: `${Math.round(p.importance * 100)}%` }} />
                      <span className="brief-text">{p.text}</span>
                      <span className="brief-src">{p.source}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
