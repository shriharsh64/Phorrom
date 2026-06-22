import { useEffect, useMemo, useState } from "react";
import {
  api,
  type AdvisorOverview,
  type BreakthroughRow,
  type LearningRow,
  type ResourceRow,
} from "../lib/api";

// Resource & Tooling Advisor panel: "Learn first" (prerequisite-ordered learning plan),
// "Resources" (free tools per stage), and a progress summary. Ideation-first by design.
export default function AdvisorPanel({ projectId }: { projectId: number }) {
  const [problem, setProblem] = useState("");
  const [tech, setTech] = useState("");
  const [taskTypes, setTaskTypes] = useState("");
  const [data, setData] = useState<AdvisorOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.advisorOverview(projectId).then(setData).catch(() => void 0);
  }, [projectId]);

  async function recommend() {
    setBusy(true);
    setError(null);
    try {
      const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
      const res = await api.advisorRecommend(projectId, {
        problem,
        tech: csv(tech),
        task_types: csv(taskTypes),
      });
      setData(res.overview);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function cycleLearning(item: LearningRow) {
    const next =
      item.status === "todo" ? "in_progress" : item.status === "in_progress" ? "done" : "todo";
    await api.setLearningStatus(item.id, next);
    setData(await api.advisorOverview(projectId));
  }

  async function toggleResource(item: ResourceRow) {
    const next = item.status === "done" ? "suggested" : "done";
    await api.setResourceStatus(item.id, next);
    setData(await api.advisorOverview(projectId));
  }

  async function cycleBreakthrough(item: BreakthroughRow) {
    const order = ["suggested", "exploring", "done", "dismissed"];
    const next = order[(order.indexOf(item.status) + 1) % order.length];
    await api.setBreakthroughStatus(item.id, next);
    setData(await api.advisorOverview(projectId));
  }

  // Group learning items by concept, preserving prerequisite order.
  const learningByConcept = useMemo(() => {
    const map = new Map<string, LearningRow[]>();
    (data?.learning ?? []).forEach((li) => {
      const arr = map.get(li.concept) ?? [];
      arr.push(li);
      map.set(li.concept, arr);
    });
    return [...map.entries()];
  }, [data]);

  const resourcesByKind = useMemo(() => {
    const map = new Map<string, ResourceRow[]>();
    (data?.resources ?? []).forEach((r) => {
      const arr = map.get(r.kind) ?? [];
      arr.push(r);
      map.set(r.kind, arr);
    });
    return [...map.entries()];
  }, [data]);

  const p = data?.progress;

  return (
    <div className="advisor">
      <div className="advisor-input">
        <textarea
          placeholder="Describe the problem you're tackling…"
          value={problem}
          onChange={(e) => setProblem(e.target.value)}
        />
        <input placeholder="tech (comma-separated, e.g. python, iot)" value={tech} onChange={(e) => setTech(e.target.value)} />
        <input placeholder="task types (e.g. sensor, model, dashboard)" value={taskTypes} onChange={(e) => setTaskTypes(e.target.value)} />
        <button onClick={() => void recommend()} disabled={busy}>
          {busy ? "Thinking…" : "Recommend resources & learning plan"}
        </button>
        {error && <div className="error">{error}</div>}
      </div>

      {p && (
        <div className="progress-row">
          <span>📚 Learn: {p.learning.done}/{p.learning.total} done · {p.learning.gaps} gap items</span>
          <span>🧰 Resources: {p.resources.done}/{p.resources.total} used</span>
          <span>🧠 Concepts: {p.concepts.mastered} mastered · {p.concepts.gap} gaps</span>
          <span>🚀 Breakthroughs: {p.breakthroughs.total}</span>
        </div>
      )}

      {(data?.breakthroughs.length ?? 0) > 0 && (
        <section className="breakthroughs">
          <h2>Breakthrough opportunities</h2>
          <p className="hint" style={{ margin: "0 0 10px", textAlign: "left" }}>
            High-leverage improvements ranked by payoff vs effort.
          </p>
          {data!.breakthroughs.map((b) => (
            <div key={b.id} className={`bt-card ${b.status}`}>
              <button className="status-dot" title={b.status} onClick={() => void cycleBreakthrough(b)}>
                {b.status === "done" ? "✓" : b.status === "exploring" ? "…" : b.status === "dismissed" ? "✕" : "○"}
              </button>
              <div className="bt-body">
                <div className="bt-title">
                  {b.title}
                  <span className="bt-score">score {b.score}</span>
                </div>
                <div className="bt-tags">
                  {b.benefit_types.map((t) => <span key={t} className={`tag benefit ${t}`}>{t}</span>)}
                  <span className="tag">impact: {b.impact}</span>
                  <span className="tag">effort: {b.effort}</span>
                </div>
                {b.rationale && <div className="meta">{b.rationale}</div>}
                {b.related_concepts.length > 0 && (
                  <div className="meta">Needs: {b.related_concepts.join(", ")}</div>
                )}
              </div>
            </div>
          ))}
        </section>
      )}

      <div className="advisor-cols">
        <section>
          <h2>Learn first</h2>
          {learningByConcept.length === 0 && <p className="hint">Run a recommendation to build your learning plan.</p>}
          {learningByConcept.map(([concept, items]) => (
            <div key={concept} className="concept-block">
              <h3>{concept}</h3>
              {items.map((li) => (
                <div key={li.id} className={`learn-item ${li.status}`}>
                  <button className="status-dot" title={li.status} onClick={() => void cycleLearning(li)}>
                    {li.status === "done" ? "✓" : li.status === "in_progress" ? "…" : "○"}
                  </button>
                  <div>
                    {li.url ? <a href={li.url} target="_blank" rel="noreferrer">{li.title}</a> : li.title}
                    {li.is_gap ? <span className="tag gap">gap</span> : null}
                    {li.source && <span className="tag">{li.source}</span>}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </section>

        <section>
          <h2>Resources</h2>
          {resourcesByKind.length === 0 && <p className="hint">Free tools, datasets, and services appear here.</p>}
          {resourcesByKind.map(([kind, items]) => (
            <div key={kind} className="concept-block">
              <h3>{kind}</h3>
              {items.map((r) => (
                <div key={r.id} className={`learn-item ${r.status === "done" ? "done" : ""}`}>
                  <button className="status-dot" onClick={() => void toggleResource(r)}>
                    {r.status === "done" ? "✓" : "○"}
                  </button>
                  <div>
                    {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.name}</a> : r.name}
                    {r.is_free ? <span className="tag free">free</span> : null}
                    {r.rationale && <div className="meta">{r.rationale}</div>}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
