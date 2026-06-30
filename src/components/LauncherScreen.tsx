import { useEffect, useState } from "react";
import { api, type AppSettings, type Project } from "../lib/api";
import NewProjectWizard from "./NewProjectWizard";

// The startup window: first-run workspace setup, then "new project" or "open existing".
export default function LauncherScreen({ onOpen }: { onOpen: (p: Project) => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [wsPath, setWsPath] = useState("");
  const [wsName, setWsName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wizard, setWizard] = useState(false);

  async function load() {
    try {
      const s = await api.getSettings();
      setSettings(s);
      setWsPath(s.workspace_path);
      setWsName(s.workspace_name);
      if (s.configured) setProjects((await api.listProjects()).projects);
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => { void load(); }, []);

  async function saveWorkspace() {
    setBusy(true); setError(null);
    try {
      await api.setWorkspace(wsPath.trim(), wsName.trim());
      await load();
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  if (settings === null) {
    return <div className="launcher"><div className="empty">Loading…</div></div>;
  }

  // ---- first run: choose where projects live ----
  if (!settings.configured) {
    return (
      <div className="launcher">
        <div className="launcher-card">
          <div className="brand-mark" style={{ width: 48, height: 48, fontSize: 22, margin: "0 auto 14px" }}>◆</div>
          <h1>Welcome to Phorrom</h1>
          <p className="hint" style={{ textAlign: "center", marginBottom: 22 }}>
            First, choose a folder where all your projects will be saved. Each project gets its own
            subfolder with prompts, exports, and documents.
          </p>
          {error && <div className="error">{error}</div>}
          <label className="field-label">Workspace name</label>
          <input type="text" value={wsName} onChange={(e) => setWsName(e.target.value)}
            placeholder="My Workspace" />
          <label className="field-label" style={{ marginTop: 14 }}>Workspace folder</label>
          <input type="text" value={wsPath} onChange={(e) => setWsPath(e.target.value)}
            placeholder={settings.default_workspace} style={{ width: "100%", fontFamily: "var(--mono)" }} />
          <p className="hint" style={{ marginTop: 6 }}>
            The folder is created if it doesn’t exist. Default: <code>{settings.default_workspace}</code>
          </p>
          <button style={{ marginTop: 18, width: "100%" }} onClick={() => void saveWorkspace()} disabled={busy}>
            {busy ? "Creating…" : "Create workspace & continue"}
          </button>
        </div>
      </div>
    );
  }

  // ---- configured: new / open ----
  return (
    <div className="launcher">
      {wizard && (
        <NewProjectWizard
          onCancel={() => setWizard(false)}
          onCreated={(p) => { setWizard(false); onOpen(p); }}
        />
      )}
      <div className="launcher-card launcher-wide">
        <div className="brand" style={{ border: "none", padding: 0, marginBottom: 6 }}>
          <span className="brand-mark">◆</span>
          <span className="brand-text">Phorrom<small>{settings.workspace_name}</small></span>
        </div>
        <p className="hint" style={{ marginBottom: 18 }}>
          Workspace: <code>{settings.workspace_path}</code>
        </p>
        {error && <div className="error">{error}</div>}

        <div className="launcher-actions">
          <button className="launcher-tile" onClick={() => setWizard(true)}>
            <span className="launcher-tile-icon">＋</span>
            <span className="launcher-tile-title">New project</span>
            <span className="launcher-tile-sub">Describe it, pick features, set keys</span>
          </button>
        </div>

        <h3 style={{ marginTop: 22 }}>Open existing project</h3>
        {projects.length === 0 && <p className="hint">No projects yet — create your first one above.</p>}
        <div className="launcher-projects">
          {projects.map((p) => (
            <button key={p.id} className="launcher-project" onClick={() => onOpen(p)}>
              <div className="launcher-project-main">
                <span className="launcher-project-name">{p.name}</span>
                {p.description && <span className="launcher-project-desc">{p.description}</span>}
              </div>
              {p.deadline && <span className="bt-score">due {p.deadline}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
