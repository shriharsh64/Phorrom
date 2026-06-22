import { useEffect, useState } from "react";
import { api, type ProblemRecord, type ProgressAssessment, type TaskRow } from "../lib/api";

// Phase 2 "Plan" view: define the problem (capability #1) and manage a prioritized,
// dependency-aware task list (capability #8).
export default function PlanPanel({ projectId }: { projectId: number }) {
  const [desc, setDesc] = useState("");
  const [problem, setProblem] = useState<ProblemRecord | null>(null);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [title, setTitle] = useState("");
  const [urgency, setUrgency] = useState(0.5);
  const [impact, setImpact] = useState(0.5);
  const [busy, setBusy] = useState(false);
  const [assessment, setAssessment] = useState<ProgressAssessment | null>(null);

  async function refresh() {
    const [p, t, a] = await Promise.all([
      api.latestProblem(projectId), api.listTasks(projectId), api.latestProgress(projectId),
    ]);
    setProblem(p.record);
    setTasks(t.tasks);
    setAssessment(a.assessment);
  }

  async function assess() {
    setAssessment(await api.assessProgress(projectId));
    await refresh();
  }

  const pct = (v: number) => `${Math.round(v * 100)}%`;
  useEffect(() => {
    void refresh();
  }, [projectId]);

  async function define() {
    if (!desc.trim()) return;
    setBusy(true);
    try {
      const r = await api.defineProblem(projectId, desc);
      setProblem(r.latest);
    } finally {
      setBusy(false);
    }
  }

  async function addTask() {
    if (!title.trim()) return;
    await api.createTask(projectId, title, urgency, impact);
    setTitle("");
    await refresh();
  }

  async function cycleStatus(t: TaskRow) {
    const order = ["todo", "in_progress", "blocked", "done"];
    await api.setTaskStatus(t.id, order[(order.indexOf(t.status) + 1) % order.length]);
    await refresh();
  }

  return (
    <div className="advisor">
      <section>
        <h2>Problem statement</h2>
        <div className="advisor-input">
          <textarea placeholder="Describe the problem you're solving…" value={desc} onChange={(e) => setDesc(e.target.value)} />
          <button onClick={() => void define()} disabled={busy}>{busy ? "Defining…" : "Define / refine"}</button>
        </div>
        {problem && (
          <div className="bt-card" style={{ borderLeftColor: "#8957e5" }}>
            <div className="bt-body">
              <div className="bt-title">{problem.statement}</div>
              {problem.gap && <div className="meta">Gap: {problem.gap}</div>}
              {problem.success_criteria.length > 0 && (
                <div className="meta">Success: {problem.success_criteria.join("; ")}</div>
              )}
              {problem.validation && <div className="meta">⚠ {problem.validation}</div>}
              {(problem.clarifying_questions?.length ?? 0) > 0 && (
                <ul className="meta" style={{ margin: "6px 0 0 16px" }}>
                  {problem.clarifying_questions!.map((q) => <li key={q}>{q}</li>)}
                </ul>
              )}
            </div>
          </div>
        )}
      </section>

      <section style={{ marginTop: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ border: "none", margin: 0 }}>Progress</h2>
          <button onClick={() => void assess()}>Assess</button>
        </div>
        {assessment ? (
          <div className="bt-card" style={{ borderLeftColor: "#3fb950" }}>
            <div className="bt-body">
              <div className="progress-row" style={{ margin: 0 }}>
                <span>✅ Completion {pct(assessment.completion)}</span>
                <span>❤️ Health {pct(assessment.health)}</span>
                <span>⚠️ {assessment.risks.length} risk(s)</span>
              </div>
              {assessment.narrative && <div className="meta">{assessment.narrative}</div>}
              {assessment.risks.map((r, i) => (
                <div key={i} className="meta">⚠ [{r.severity}] {r.detail}</div>
              ))}
              {assessment.recommendations.map((rec, i) => (
                <div key={i} className="meta">→ {rec}</div>
              ))}
            </div>
          </div>
        ) : (
          <p className="hint" style={{ textAlign: "left" }}>Run an assessment to score milestones, flag risks, and get next steps.</p>
        )}
      </section>

      <section style={{ marginTop: 18 }}>
        <h2>Tasks (auto-prioritized)</h2>
        <div className="task-add">
          <input placeholder="New task…" value={title} onChange={(e) => setTitle(e.target.value)} />
          <label>urgency {urgency.toFixed(1)}<input type="range" min={0} max={1} step={0.1} value={urgency} onChange={(e) => setUrgency(+e.target.value)} /></label>
          <label>impact {impact.toFixed(1)}<input type="range" min={0} max={1} step={0.1} value={impact} onChange={(e) => setImpact(+e.target.value)} /></label>
          <button onClick={() => void addTask()}>Add</button>
        </div>
        {tasks.length === 0 && <p className="hint">No tasks yet.</p>}
        {tasks.map((t) => (
          <div key={t.id} className={`learn-item ${t.status === "done" ? "done" : ""}`}>
            <button className="status-dot" title={t.status} onClick={() => void cycleStatus(t)}>
              {t.status === "done" ? "✓" : t.status === "in_progress" ? "…" : t.status === "blocked" ? "✕" : "○"}
            </button>
            <div>
              {t.title}
              <span className="tag">P {t.priority?.toFixed(2) ?? "—"}</span>
              {t.ready === false && t.status !== "done" && <span className="tag">blocked-by-deps</span>}
              {(t.blocks ?? 0) > 0 && <span className="tag">unblocks {t.blocks}</span>}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
