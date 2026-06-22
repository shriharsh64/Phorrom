import { useEffect, useState } from "react";
import { api, type CloudStatus, type ProviderInfo, type Snapshot } from "../lib/api";
import { isTauri, secretStatus, setSecret } from "../lib/tauri";

// Provider keys: stored in the OS keychain (desktop) and applied to the running sidecar
// immediately. In a plain browser there's no keychain, so keys apply only for the session.
const PROVIDERS = [
  { key: "gemini" as const, env: "GEMINI_API_KEY", label: "Google AI Studio (Gemini)", where: "aistudio.google.com" },
  { key: "groq" as const, env: "GROQ_API_KEY", label: "Groq", where: "console.groq.com" },
  { key: "openrouter" as const, env: "OPENROUTER_API_KEY", label: "OpenRouter", where: "openrouter.ai" },
];

export default function SettingsPanel() {
  const [stored, setStored] = useState<Record<string, boolean>>({});
  const [avail, setAvail] = useState<Record<string, boolean>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);

  // --- cloud backup state ---
  const [cloud, setCloud] = useState<CloudStatus | null>(null);
  const [snaps, setSnaps] = useState<Snapshot[]>([]);
  const [pass, setPass] = useState("");
  const [cloudMsg, setCloudMsg] = useState<string | null>(null);
  const [cloudBusy, setCloudBusy] = useState(false);

  async function refresh() {
    setStored(await secretStatus());
    const p = await api.providers();
    setAvail(Object.fromEntries(p.providers.map((x: ProviderInfo) => [x.provider, x.available])));
  }
  async function refreshCloud() {
    const st = await api.cloudStatus();
    setCloud(st);
    if (st.connected) setSnaps((await api.cloudSnapshots()).snapshots ?? []);
  }
  useEffect(() => {
    void refresh();
    void refreshCloud();
  }, []);

  async function connect() {
    setCloudBusy(true); setCloudMsg("Complete the Google sign-in in your browser…");
    try {
      const r = await api.cloudConnect();
      setCloudMsg(r.ok ? `Connected as ${r.email ?? "Google account"}.` : r.error ?? "Failed");
      await refreshCloud();
    } catch (e) { setCloudMsg(String(e)); }
    finally { setCloudBusy(false); }
  }
  async function disconnect() { await api.cloudDisconnect(); setCloudMsg("Disconnected."); await refreshCloud(); }
  async function backup() {
    if (!pass) { setCloudMsg("Enter an encryption passphrase first."); return; }
    setCloudBusy(true);
    try {
      const r = await api.cloudBackup(pass);
      setCloudMsg(r.ok ? `Backed up: ${r.snapshot?.name}` : r.error ?? "Backup failed");
      await refreshCloud();
    } finally { setCloudBusy(false); }
  }
  async function restore(s: Snapshot) {
    if (!pass) { setCloudMsg("Enter the passphrase used for that backup."); return; }
    if (!confirm(`Restore "${s.name}"? This overwrites local data (effective after restart).`)) return;
    setCloudBusy(true);
    try {
      const r = await api.cloudRestore(s.id, pass);
      setCloudMsg(r.ok ? (r.note ?? "Restored.") : r.error ?? "Restore failed");
    } finally { setCloudBusy(false); }
  }

  async function save(envName: string, provKey: "gemini" | "groq" | "openrouter") {
    const value = values[provKey] ?? "";
    await setSecret(envName, value);                 // persist to keychain (no-op in browser)
    await api.setProviderKeys({ [provKey]: value }); // apply to the running sidecar now
    setValues((v) => ({ ...v, [provKey]: "" }));
    setMsg(value ? `Saved ${envName}.` : `Cleared ${envName}.`);
    await refresh();
  }

  return (
    <div className="advisor">
      <section>
        <h2>Provider API keys</h2>
        {!isTauri() && (
          <p className="hint" style={{ textAlign: "left" }}>
            Browser mode: keys apply to the running sidecar but aren’t saved to the OS keychain.
            Use the desktop app to persist them securely.
          </p>
        )}
        {PROVIDERS.map((p) => (
          <div key={p.key} className="bt-card" style={{ borderLeftColor: avail[p.key] ? "#3fb950" : "#6e7681" }}>
            <div className="bt-body">
              <div className="bt-title">
                {p.label}
                <span className="bt-score">
                  {avail[p.key] ? "active" : "inactive"}{stored[p.env] ? " · stored" : ""}
                </span>
              </div>
              <div className="meta">free key from {p.where}</div>
              <div className="task-add" style={{ marginTop: 6 }}>
                <input
                  type="password"
                  placeholder={stored[p.env] ? "•••••••• (stored — type to replace)" : `${p.env}…`}
                  value={values[p.key] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [p.key]: e.target.value }))}
                />
                <button onClick={() => void save(p.env, p.key)}>
                  {(values[p.key] ?? "") ? "Save" : "Clear"}
                </button>
              </div>
            </div>
          </div>
        ))}
        {msg && <p className="hint" style={{ textAlign: "left" }}>{msg}</p>}
        <p className="hint" style={{ textAlign: "left" }}>
          Local models (Ollama) and the mock provider need no key and are always available.
        </p>
      </section>

      <section style={{ marginTop: 18 }}>
        <h2>Cloud backup (Google Drive)</h2>
        <div className="bt-card" style={{ borderLeftColor: cloud?.connected ? "#3fb950" : "#6e7681" }}>
          <div className="bt-body">
            <div className="bt-title">
              {cloud?.connected ? `Connected — ${cloud.email ?? "Google account"}` : "Not connected"}
              <span className="bt-score">{cloud?.credentials_present ? "credentials ✓" : "credentials.json missing"}</span>
            </div>
            <div className="task-add" style={{ marginTop: 8 }}>
              {cloud?.connected
                ? <button className="btn-ghost" onClick={() => void disconnect()} disabled={cloudBusy}>Disconnect</button>
                : <button onClick={() => void connect()} disabled={cloudBusy || !cloud?.credentials_present}>Connect Google account</button>}
            </div>
            <div className="meta">Backups are encrypted on this device with your passphrase before upload — Drive never sees plaintext.</div>
          </div>
        </div>

        <div className="task-add">
          <input type="password" placeholder="encryption passphrase…" value={pass} onChange={(e) => setPass(e.target.value)} />
          <button onClick={() => void backup()} disabled={cloudBusy || !cloud?.connected}>Back up now</button>
        </div>

        {cloud?.connected && (
          <>
            <h3>Snapshots</h3>
            {snaps.length === 0 && <p className="hint" style={{ textAlign: "left" }}>No backups yet.</p>}
            {snaps.map((s) => (
              <div key={s.id} className="learn-item">
                <span className="status-dot" style={{ cursor: "default" }}>☁</span>
                <div style={{ flex: 1, display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <span>{s.name}</span>
                  <button className="btn-ghost" onClick={() => void restore(s)} disabled={cloudBusy}>Restore</button>
                </div>
              </div>
            ))}
          </>
        )}
        {cloudMsg && <p className="hint" style={{ textAlign: "left" }}>{cloudMsg}</p>}
      </section>
    </div>
  );
}
