import { useEffect, useRef, useState } from "react";
import { api, type Message, type Project, type ProviderInfo } from "./lib/api";
import AdvisorPanel from "./components/AdvisorPanel";
import PlanPanel from "./components/PlanPanel";
import OrchestratorPanel from "./components/OrchestratorPanel";
import IdeationPanel from "./components/IdeationPanel";
import ResearchPanel from "./components/ResearchPanel";

interface Turn extends Message {
  meta?: string;
}

type Tab = "chat" | "plan" | "ideation" | "research" | "orchestrator" | "advisor";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);

  // Load projects; create a default one on first run so the app is usable immediately.
  useEffect(() => {
    api.listProjects().then(async ({ projects }) => {
      if (projects.length === 0) {
        const p = await api.createProject("My Project");
        setProjects([p]);
        setProjectId(p.id);
      } else {
        setProjects(projects);
        setProjectId(projects[0].id);
      }
    });
  }, []);

  async function newProject() {
    const name = prompt("Project name?");
    if (!name) return;
    const p = await api.createProject(name);
    setProjects((ps) => [...ps, p]);
    setProjectId(p.id);
  }
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [provider, setProvider] = useState("mock");
  const [model, setModel] = useState("mock-small");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .providers()
      .then((r) => setProviders(r.providers))
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const current = providers.find((p) => p.provider === provider);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setError(null);
    setBusy(true);
    const userTurn: Turn = { role: "user", content: text };
    const history: Message[] = [...turns, userTurn].map((t) => ({
      role: t.role,
      content: t.content,
    }));
    setTurns((t) => [...t, userTurn]);
    setInput("");
    try {
      const res = await api.chat(history, provider, model);
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: res.text,
          meta: `${res.provider}/${res.model} · ${res.tokens_in}+${res.tokens_out} tok · ${Math.round(res.latency_ms)}ms`,
        },
      ]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>Phorrom</h1>
        <nav className="tabs">
          <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>Chat</button>
          <button className={tab === "plan" ? "active" : ""} onClick={() => setTab("plan")}>Plan</button>
          <button className={tab === "ideation" ? "active" : ""} onClick={() => setTab("ideation")}>Ideation</button>
          <button className={tab === "research" ? "active" : ""} onClick={() => setTab("research")}>Research</button>
          <button className={tab === "orchestrator" ? "active" : ""} onClick={() => setTab("orchestrator")}>Orchestrator</button>
          <button className={tab === "advisor" ? "active" : ""} onClick={() => setTab("advisor")}>Advisor</button>
        </nav>
        <div className="project-picker">
          <select value={projectId ?? ""} onChange={(e) => setProjectId(Number(e.target.value))}>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button onClick={() => void newProject()} title="New project">＋</button>
        </div>
        <div className="controls" style={{ visibility: tab === "chat" ? "visible" : "hidden" }}>
          <select
            value={provider}
            onChange={(e) => {
              const p = e.target.value;
              setProvider(p);
              const found = providers.find((x) => x.provider === p);
              if (found?.models.length) setModel(found.models[0]);
            }}
          >
            {providers.map((p) => (
              <option key={p.provider} value={p.provider} disabled={!p.available}>
                {p.provider} {p.available ? "" : "(unavailable)"}
              </option>
            ))}
          </select>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {(current?.models ?? [model]).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      </header>

      {projectId === null ? (
        <p className="hint" style={{ marginTop: 40 }}>Loading project…</p>
      ) : tab === "advisor" ? (
        <AdvisorPanel projectId={projectId} />
      ) : tab === "plan" ? (
        <PlanPanel projectId={projectId} />
      ) : tab === "ideation" ? (
        <IdeationPanel projectId={projectId} />
      ) : tab === "research" ? (
        <ResearchPanel projectId={projectId} />
      ) : tab === "orchestrator" ? (
        <OrchestratorPanel projectId={projectId} />
      ) : (
        <>
      {error && <div className="error">{error}</div>}

      <main className="messages">
        {turns.length === 0 && <p className="hint">Say hello to your project co-pilot.</p>}
        {turns.map((t, i) => (
          <div key={i} className={`msg ${t.role}`}>
            <div className="bubble">{t.content}</div>
            {t.meta && <div className="meta">{t.meta}</div>}
          </div>
        ))}
        <div ref={bottom} />
      </main>

      <footer>
        <textarea
          value={input}
          placeholder="Type a message…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button onClick={() => void send()} disabled={busy}>
          {busy ? "…" : "Send"}
        </button>
      </footer>
      </>
      )}
    </div>
  );
}
