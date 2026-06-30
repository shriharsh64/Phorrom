import { useEffect, useState } from "react";
import { api, type IdeaRow } from "../lib/api";
import FeatureBrief from "./FeatureBrief";

// Capability #2: generate & rank ideas; each idea's required concepts the user hasn't mastered
// become 'gap' concepts that the Advisor tab then turns into a learning plan.
export default function IdeationPanel({ projectId }: { projectId: number }) {
  const [prompt, setPrompt] = useState("");
  const [ideas, setIdeas] = useState<IdeaRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listIdeas(projectId).then((r) => setIdeas(r.ideas)).catch(() => void 0);
  }, [projectId]);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.ideate(projectId, prompt || undefined);
      setIdeas(r.ideas);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function cycle(idea: IdeaRow) {
    const order = ["suggested", "selected", "dismissed"];
    await api.setIdeaStatus(idea.id, order[(order.indexOf(idea.status) + 1) % order.length]);
    setIdeas((await api.listIdeas(projectId)).ideas);
  }

  const bar = (label: string, v: number | null) => (
    <span className="metric">
      {label}
      <span className="metric-bar"><span style={{ width: `${Math.round((v ?? 0) * 100)}%` }} /></span>
    </span>
  );

  return (
    <div className="advisor">
      <FeatureBrief projectId={projectId} feature="ideation" />
      <div className="advisor-input">
        <textarea placeholder="Optional focus for ideation (defaults to the project's problem statement)…" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        <button onClick={() => void generate()} disabled={busy}>{busy ? "Ideating…" : "Generate ideas"}</button>
        {error && <div className="error">{error}</div>}
      </div>

      <section>
        <h2>Ideas (ranked)</h2>
        {ideas.length === 0 && <p className="hint">Generate ideas grounded in your problem statement.</p>}
        {ideas.map((idea) => (
          <div key={idea.id} className={`bt-card ${idea.status === "dismissed" ? "dismissed" : idea.status === "selected" ? "done" : ""}`}>
            <button className="status-dot" title={idea.status} onClick={() => void cycle(idea)}>
              {idea.status === "selected" ? "★" : idea.status === "dismissed" ? "✕" : "○"}
            </button>
            <div className="bt-body">
              <div className="bt-title">{idea.title}<span className="bt-score">score {idea.score}</span></div>
              {idea.description && <div className="meta">{idea.description}</div>}
              <div className="bt-tags metrics">
                {bar("feasibility", idea.feasibility)}
                {bar("novelty", idea.novelty)}
                {bar("relevance", idea.relevance)}
              </div>
              {idea.rationale && <div className="meta">{idea.rationale}</div>}
              {idea.required_concepts.length > 0 && (
                <div className="meta">Needs (→ becomes learning gaps): {idea.required_concepts.join(", ")}</div>
              )}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
