import { useEffect, useRef, useState } from "react";
import { api, type Message, type Project, type ProviderInfo } from "./lib/api";
import AdvisorPanel from "./components/AdvisorPanel";
import PlanPanel from "./components/PlanPanel";
import OrchestratorPanel from "./components/OrchestratorPanel";
import IdeationPanel from "./components/IdeationPanel";
import ResearchPanel from "./components/ResearchPanel";
import DashboardPanel from "./components/DashboardPanel";
import SettingsPanel from "./components/SettingsPanel";
import DocsPanel from "./components/DocsPanel";

interface Turn extends Message {
  meta?: string;
}

type Tab =
  | "chat" | "plan" | "ideation" | "research"
  | "orchestrator" | "advisor" | "docs"
  | "dashboard" | "settings";

interface ViewMeta {
  label: string;
  icon: string;
  title: string;
  subtitle: string;
  group: string;
}

const VIEWS: Record<Tab, ViewMeta> = {
  chat: { label: "Chat", icon: "💬", title: "Chat", subtitle: "Converse with your project co-pilot", group: "Workspace" },
  plan: { label: "Plan", icon: "🗂️", title: "Plan", subtitle: "Problem statement, tasks & progress", group: "Workspace" },
  ideation: { label: "Ideation", icon: "💡", title: "Ideation", subtitle: "Generate, score & rank concepts", group: "Workspace" },
  research: { label: "Research", icon: "🔬", title: "Prior-art research", subtitle: "Search the literature & map white space", group: "Workspace" },
  orchestrator: { label: "Orchestrator", icon: "🧩", title: "Orchestrator", subtitle: "Decompose, budget & route across models", group: "Build" },
  advisor: { label: "Advisor", icon: "🧭", title: "Resource advisor", subtitle: "Tools, learning plan & breakthroughs", group: "Build" },
  docs: { label: "Docs", icon: "📄", title: "Documents", subtitle: "Generate reports & extract from media", group: "Build" },
  dashboard: { label: "Dashboard", icon: "📊", title: "Dashboard", subtitle: "Provider health, tokens & estimators", group: "System" },
  settings: { label: "Settings", icon: "⚙️", title: "Settings", subtitle: "Provider keys & cloud backup", group: "System" },
};

const GROUPS = ["Workspace", "Build", "System"];

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);

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

  // --- chat state ---
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [provider, setProvider] = useState("mock");
  const [model, setModel] = useState("mock-small");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [optimize, setOptimize] = useState(false);
  const [depth, setDepth] = useState("standard");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.providers().then((r) => setProviders(r.providers)).catch((e) => setError(String(e)));
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
    const history: Message[] = [...turns, userTurn].map((t) => ({ role: t.role, content: t.content }));
    setTurns((t) => [...t, userTurn]);
    setInput("");
    try {
      if (optimize) {
        const r = await api.optimize(text, depth, provider, model, projectId ?? undefined);
        setTurns((t) => [...t, { role: "assistant", content: r.text,
          meta: `optimized · score ${r.score} · ${r.iterations} pass(es) · relevance ${r.relevance}` }]);
      } else {
        const res = await api.chat(history, provider, model);
        setTurns((t) => [...t, { role: "assistant", content: res.text,
          meta: `${res.provider}/${res.model} · ${res.tokens_in}+${res.tokens_out} tok · ${Math.round(res.latency_ms)}ms` }]);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const meta = VIEWS[tab];

  function renderView() {
    if (tab === "chat") return renderChat();
    if (tab === "dashboard") return <DashboardPanel />;
    if (tab === "settings") return <SettingsPanel />;
    if (projectId === null) return <div className="empty">Loading project…</div>;
    switch (tab) {
      case "plan": return <PlanPanel projectId={projectId} />;
      case "ideation": return <IdeationPanel projectId={projectId} />;
      case "research": return <ResearchPanel projectId={projectId} />;
      case "orchestrator": return <OrchestratorPanel projectId={projectId} />;
      case "advisor": return <AdvisorPanel projectId={projectId} />;
      case "docs": return <DocsPanel projectId={projectId} />;
    }
  }

  function renderChat() {
    return (
      <div className="chat">
        {error && <div className="banner banner-error">{error}</div>}
        <div className="chat-log">
          {turns.length === 0 && (
            <div className="empty">
              <div className="empty-icon">💬</div>
              <p>Say hello to your project co-pilot.</p>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={`msg ${t.role}`}>
              <div className="bubble">{t.content}</div>
              {t.meta && <div className="msg-meta">{t.meta}</div>}
            </div>
          ))}
          <div ref={bottom} />
        </div>
        <div className="composer">
          <textarea
            value={input}
            placeholder="Type a message…  (Enter to send, Shift+Enter for newline)"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); }
            }}
          />
          <button className="btn btn-primary" onClick={() => void send()} disabled={busy}>
            {busy ? "…" : "Send"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <span className="brand-text">Phorrom<small>AI project co-pilot</small></span>
        </div>
        <nav className="nav">
          {GROUPS.map((g) => (
            <div key={g} className="nav-group">
              <div className="nav-group-label">{g}</div>
              {(Object.keys(VIEWS) as Tab[]).filter((k) => VIEWS[k].group === g).map((k) => (
                <button key={k} className={`nav-item ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
                  <span className="nav-icon">{VIEWS[k].icon}</span>
                  <span>{VIEWS[k].label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <label className="field-label">Project</label>
          <div className="project-picker">
            <select value={projectId ?? ""} onChange={(e) => setProjectId(Number(e.target.value))}>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button className="btn btn-ghost" onClick={() => void newProject()} title="New project">＋</button>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{meta.title}</h1>
            <p>{meta.subtitle}</p>
          </div>
          {tab === "chat" && (
            <div className="chat-controls">
              <select className="select" value={provider} onChange={(e) => {
                const p = e.target.value; setProvider(p);
                const found = providers.find((x) => x.provider === p);
                if (found?.models.length) setModel(found.models[0]);
              }}>
                {providers.map((p) => (
                  <option key={p.provider} value={p.provider} disabled={!p.available}>
                    {p.provider}{p.available ? "" : " (off)"}
                  </option>
                ))}
              </select>
              <select className="select" value={model} onChange={(e) => setModel(e.target.value)}>
                {(current?.models ?? [model]).map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <label className="switch" title="Self-evaluate & recalibrate (capability #10)">
                <input type="checkbox" checked={optimize} onChange={(e) => setOptimize(e.target.checked)} />
                <span>optimize</span>
              </label>
              {optimize && (
                <select className="select" value={depth} onChange={(e) => setDepth(e.target.value)}>
                  <option value="brief">brief</option>
                  <option value="standard">standard</option>
                  <option value="deep">deep</option>
                </select>
              )}
            </div>
          )}
        </header>
        <section className="view">{renderView()}</section>
      </main>
    </div>
  );
}
