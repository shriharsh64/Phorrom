import { useEffect, useState } from "react";
import { api, type DashboardData, type MlStatus } from "../lib/api";

// Dashboard: provider health (circuit-breaker state), token ledger, and learned-estimator status.
export default function DashboardPanel() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [ml, setMl] = useState<MlStatus | null>(null);
  const [training, setTraining] = useState(false);
  const [mlError, setMlError] = useState<string | null>(null);

  async function refresh() {
    setData(await api.dashboard());
    setMl(await api.mlStatus());
  }
  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 5000); // live-ish health
    return () => clearInterval(id);
  }, []);

  async function train() {
    setTraining(true);
    setMlError(null);
    try {
      await api.mlTrain();
      await refresh();
    } catch (e) {
      setMlError(String(e));
    } finally {
      setTraining(false);
    }
  }

  const circuitColor = (s: string) =>
    s === "open" ? "#f85149" : s === "half_open" ? "#d29922" : "#3fb950";

  const total = data?.tokens.total ?? 0;

  return (
    <div className="advisor">
      <section>
        <h2>Provider health</h2>
        {!data && <p className="hint">Loading…</p>}
        {data?.providers.map((p) => (
          <div key={p.provider} className="learn-item">
            <span className="status-dot" style={{ cursor: "default", color: p.available ? "#3fb950" : "#6e7681", borderColor: p.available ? "#3fb950" : "#30363d" }}>
              {p.available ? "●" : "○"}
            </span>
            <div>
              <b>{p.provider}</b>
              <span className="tag">{p.models} models</span>
              <span className="tag" style={{ color: circuitColor(p.circuit) }}>circuit: {p.circuit}</span>
              {p.fails > 0 && <span className="tag">{p.fails} fails</span>}
            </div>
          </div>
        ))}
      </section>

      <section style={{ marginTop: 18 }}>
        <h2>Token ledger</h2>
        <div className="progress-row"><span>Σ total consumed: <b>{total}</b> tokens</span></div>
        {Object.entries(data?.tokens.by_provider ?? {}).map(([prov, n]) => (
          <div key={prov} className="learn-item">
            <span className="status-dot" style={{ cursor: "default" }}>{" "}</span>
            <div style={{ width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span>{prov}</span><span className="meta">{n} tok</span>
              </div>
              <div className="metric-bar"><span style={{ width: `${total ? Math.round((n / total) * 100) : 0}%` }} /></div>
            </div>
          </div>
        ))}
        {total === 0 && <p className="hint">No token usage recorded yet — run a chat or orchestration.</p>}
      </section>

      <section style={{ marginTop: 18 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ border: "none", margin: 0 }}>Learned estimators</h2>
          <button onClick={() => void train()} disabled={training}>{training ? "Training…" : "Train"}</button>
        </div>
        {mlError && <div className="error">{mlError}</div>}
        <div className="progress-row">
          <span>{ml?.trained ? "✅ trained" : "○ heuristic (untrained)"}</span>
          <span>📊 {ml?.samples ?? 0} samples</span>
          {ml?.metrics && <span>token R² {ml.metrics.token_r2.toFixed(2)} · MAE {ml.metrics.token_mae.toFixed(0)}</span>}
          {ml?.metrics && <span>quality R² {ml.metrics.quality_r2.toFixed(2)}</span>}
        </div>
        <p className="hint" style={{ textAlign: "left", margin: 0 }}>
          Samples accrue when you orchestrate with “execute”. Once trained, run the orchestrator with the learned router.
        </p>
      </section>
    </div>
  );
}
