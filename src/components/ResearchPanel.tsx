import { useEffect, useState } from "react";
import { api, type ResearchResultRow, type ResearchSummary } from "../lib/api";

// Capability #4: prior-art search across free sources (arXiv + Semantic Scholar) with a
// grounded white-space summary. Results are real retrievals — nothing is fabricated.
export default function ResearchPanel({ projectId }: { projectId: number }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ResearchResultRow[]>([]);
  const [summary, setSummary] = useState<ResearchSummary | null>(null);
  const [whiteSpace, setWhiteSpace] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.researchResults(projectId).then((r) => {
      setResults(r.results);
      setSummary(r.summary);
      setWhiteSpace(r.summary?.white_space ?? null);
    }).catch(() => void 0);
  }, [projectId]);

  async function run() {
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.priorArt(projectId, query);
      setResults(r.results);
      setSummary({ query: r.query, summary: r.summary, white_space: r.white_space, n_results: r.n_results, grounded: r.grounded });
      setWhiteSpace(r.white_space);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="advisor">
      <div className="advisor-input">
        <input placeholder="Search prior art (e.g. 'low-cost soil moisture sensing')" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button onClick={() => void run()} disabled={busy}>{busy ? "Searching…" : "Search prior art"}</button>
        {error && <div className="error">{error}</div>}
      </div>

      {summary?.summary && (
        <div className="bt-card" style={{ borderLeftColor: "#3fb950" }}>
          <div className="bt-body">
            <div className="bt-title">White-space summary<span className="bt-score">{summary.n_results} sources · {summary.grounded ? "grounded" : "ungrounded"}</span></div>
            <div className="meta" style={{ whiteSpace: "pre-wrap" }}>{summary.summary}</div>
            {whiteSpace && <div className="meta" style={{ whiteSpace: "pre-wrap" }}>🔭 {whiteSpace}</div>}
          </div>
        </div>
      )}

      <section>
        <h2>Retrieved results</h2>
        {results.length === 0 && <p className="hint">No results yet — search a topic to map the prior art.</p>}
        {results.map((r, i) => (
          <div key={r.id ?? i} className="learn-item">
            <span className="status-dot" style={{ cursor: "default" }}>{i + 1}</span>
            <div>
              {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : r.title}
              <span className="tag">{r.source}</span>
              {r.year && <span className="tag">{r.year}</span>}
              {r.authors.length > 0 && <div className="meta">{r.authors.slice(0, 4).join(", ")}</div>}
              {r.abstract && <div className="meta">{r.abstract.slice(0, 180)}…</div>}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
