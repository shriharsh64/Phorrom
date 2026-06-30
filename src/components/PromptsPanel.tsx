import { useEffect, useState } from "react";
import { api, type FeatureCatalogItem } from "../lib/api";

// Shows the per-feature prompts generated from the project's setup. Each is shaped the specific
// way that feature consumes input, ready to copy into Chat/Plan/Ideation/etc.
export default function PromptsPanel({ projectId }: { projectId: number }) {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [features, setFeatures] = useState<FeatureCatalogItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  async function load() {
    const r = await api.getPrompts(projectId);
    setPrompts(r.prompts);
    setFeatures(r.features);
  }
  useEffect(() => { void load(); }, [projectId]);

  async function regenerate() {
    setBusy(true);
    try { setPrompts((await api.regeneratePrompts(projectId)).prompts); }
    finally { setBusy(false); }
  }

  async function copy(key: string) {
    try {
      await navigator.clipboard.writeText(prompts[key] ?? "");
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1500);
    } catch { /* clipboard unavailable */ }
  }

  return (
    <div className="advisor">
      <section>
        <h2>Feature prompts</h2>
        <p className="hint" style={{ textAlign: "left", marginBottom: 14 }}>
          A tailored prompt for every feature, generated from your project setup. Copy one into the
          matching tab — each is written the way that feature expects its input.
        </p>
        <div className="task-add">
          <button onClick={() => void regenerate()} disabled={busy}>
            {busy ? "Regenerating…" : "Regenerate from current setup"}
          </button>
        </div>
        {features.map((f) => (
          <div key={f.key} className="bt-card" style={{ flexDirection: "column", alignItems: "stretch" }}>
            <div className="bt-title">
              {f.label}
              <button className="btn-ghost" onClick={() => void copy(f.key)}>
                {copied === f.key ? "Copied ✓" : "Copy"}
              </button>
            </div>
            <div className="meta">How it consumes input: {f.demands}</div>
            <div className="doc-preview" style={{ marginTop: 8 }}>{prompts[f.key] ?? "—"}</div>
          </div>
        ))}
      </section>
    </div>
  );
}
