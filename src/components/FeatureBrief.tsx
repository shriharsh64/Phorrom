import { useCallback, useEffect, useState } from "react";
import { api, type FeatureBrief as Brief } from "../lib/api";

// Compact "preliminary response" banner shown at the top of each feature panel. It seeds the
// feature from the project description and live-updates as the chat conversation evolves
// (App dispatches a "phorrom:briefs-updated" event after each exchange).
export default function FeatureBrief({ projectId, feature }: { projectId: number; feature: string }) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [open, setOpen] = useState(true);
  const [flash, setFlash] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.getBriefs(projectId);
      setBrief(r.briefs[feature] ?? null);
    } catch { /* sidecar offline */ }
  }, [projectId, feature]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    function onUpdate(e: Event) {
      const d = (e as CustomEvent).detail as { projectId: number; changed: string[] };
      if (d?.projectId !== projectId) return;
      void load();
      if (d.changed?.includes(feature)) {
        setFlash(true);
        setTimeout(() => setFlash(false), 1600);
      }
    }
    window.addEventListener("phorrom:briefs-updated", onUpdate);
    return () => window.removeEventListener("phorrom:briefs-updated", onUpdate);
  }, [projectId, feature, load]);

  if (!brief) return null;
  const points = [...brief.points].sort((a, b) => b.importance - a.importance);

  return (
    <div className={`brief-banner ${flash ? "flash" : ""}`}>
      <div className="brief-head" onClick={() => setOpen((o) => !o)}>
        <span className="brief-label">Preliminary response{flash ? " · updated from chat" : ""}</span>
        <span className="bt-score">{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <>
          <p className="brief-summary">{brief.summary}</p>
          {points.length > 0 && (
            <ul className="brief-points">
              {points.map((p, i) => (
                <li key={i} title={`importance ${p.importance.toFixed(2)} · ${p.source}`}>
                  <span className="brief-bar" style={{ width: `${Math.round(p.importance * 100)}%` }} />
                  <span className="brief-text">{p.text}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
