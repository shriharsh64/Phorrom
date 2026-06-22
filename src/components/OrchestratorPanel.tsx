import { useState } from "react";
import { api, type OrchestrateResult } from "../lib/api";

// Phase 3 flagship view: decompose a task into a subtask DAG, then show how the budget
// optimizer reserves tokens for future work and routes each ready subtask to a model.
export default function OrchestratorPanel({ projectId }: { projectId: number }) {
  const [task, setTask] = useState("");
  const [budget, setBudget] = useState(4000);
  const [execute, setExecute] = useState(false);
  const [res, setRes] = useState<OrchestrateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!task.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setRes(await api.orchestrate(projectId, task, budget, execute));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const pickFor = (id: string) => res?.assignments.find((a) => a.subtask === id);
  const b = res?.budget;

  return (
    <div className="advisor">
      <div className="advisor-input">
        <textarea placeholder="Describe a task to decompose & orchestrate…" value={task} onChange={(e) => setTask(e.target.value)} />
        <div className="task-add">
          <label>token budget
            <input type="number" value={budget} min={0} step={500} onChange={(e) => setBudget(+e.target.value)} />
          </label>
          <label style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={execute} onChange={(e) => setExecute(e.target.checked)} /> execute now
          </label>
          <button onClick={() => void run()} disabled={busy}>{busy ? "Orchestrating…" : "Decompose & route"}</button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>

      {b && (
        <div className="progress-row">
          <span>💰 Budget {b.total}</span>
          <span>🔒 Reserved {b.reserved} (future)</span>
          <span>✅ Available {b.available}</span>
          <span>🔥 Spent {b.total_metered_tokens} metered</span>
          <span>🧮 {b.method}</span>
          <span>🛣️ critical path {res!.critical_path}</span>
        </div>
      )}

      {res && (
        <section>
          <h2>Subtask DAG &amp; routing</h2>
          {res.subtasks.map((s) => {
            const pick = pickFor(s.id);
            const ready = res.ready.includes(s.id);
            return (
              <div key={s.id} className="bt-card" style={{ borderLeftColor: ready ? "#1f6feb" : "#6e7681" }}>
                <div className="bt-body">
                  <div className="bt-title">
                    {s.id} <span className="tag">{s.type}</span>
                    {ready ? <span className="tag free">ready</span> : <span className="tag">waiting</span>}
                    <span className="bt-score">{s.size_hint} tok · v{s.value} · p{s.p_required}</span>
                  </div>
                  {s.description && <div className="meta">{s.description}</div>}
                  {s.depends_on.length > 0 && <div className="meta">depends on: {s.depends_on.join(", ")}</div>}
                  {pick ? (
                    <div className="meta">
                      → routed to <b>{pick.provider}/{pick.model}</b> (quality {pick.quality}
                      {pick.metered ? `, ${pick.tokens} metered tok` : ", free/local"})
                    </div>
                  ) : ready ? (
                    <div className="meta">→ unassigned (budget/quota exhausted — protected for future work)</div>
                  ) : null}
                  {res.outputs[s.id] && <div className="meta">output: {res.outputs[s.id].slice(0, 120)}</div>}
                </div>
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
