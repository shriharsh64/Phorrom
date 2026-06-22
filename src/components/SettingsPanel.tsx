import { useEffect, useState } from "react";
import { api, type ProviderInfo } from "../lib/api";
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

  async function refresh() {
    setStored(await secretStatus());
    const p = await api.providers();
    setAvail(Object.fromEntries(p.providers.map((x: ProviderInfo) => [x.provider, x.available])));
  }
  useEffect(() => {
    void refresh();
  }, []);

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
    </div>
  );
}
