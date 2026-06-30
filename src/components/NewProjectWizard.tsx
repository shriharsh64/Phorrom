import { useState } from "react";
import { api, type Project, type ProjectFeature } from "../lib/api";
import { isTauri, setSecret } from "../lib/tauri";

// Provider keys the app can store; suggestions outside this set are shown as informational notes.
const KEYABLE: Record<string, { env: string; label: string; where: string }> = {
  gemini: { env: "GEMINI_API_KEY", label: "Google AI Studio (Gemini)", where: "aistudio.google.com" },
  groq: { env: "GROQ_API_KEY", label: "Groq", where: "console.groq.com" },
  openrouter: { env: "OPENROUTER_API_KEY", label: "OpenRouter", where: "openrouter.ai" },
};

const DETAIL_FIELDS = [
  { key: "domain", label: "Domain / industry", placeholder: "e.g. healthcare, fintech, education" },
  { key: "audience", label: "Target audience", placeholder: "who is this for?" },
  { key: "tech_stack", label: "Preferred tech stack", placeholder: "e.g. React + FastAPI + Postgres" },
  { key: "constraints", label: "Key constraints", placeholder: "budget, privacy, offline, timeline…" },
];

const STEPS = ["Basics", "Features", "Keys & details", "Review"];

export default function NewProjectWizard({
  onCreated,
  onCancel,
}: {
  onCreated: (p: Project) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [deadline, setDeadline] = useState("");
  const [features, setFeatures] = useState<ProjectFeature[]>([]);
  const [suggestedKeys, setSuggestedKeys] = useState<string[]>([]);
  const [keyValues, setKeyValues] = useState<Record<string, string>>({});
  const [details, setDetails] = useState<Record<string, string>>({});
  const [newFeat, setNewFeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function suggest() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.suggestFeatures(description, deadline || null);
      setFeatures(r.features);
      setSuggestedKeys(r.suggested_api_keys);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function toggleFeature(i: number) {
    setFeatures((fs) => fs.map((f, j) => (j === i ? { ...f, enabled: !f.enabled } : f)));
  }
  function addFeature() {
    const n = newFeat.trim();
    if (!n) return;
    setFeatures((fs) => [...fs, { name: n, description: "", enabled: true }]);
    setNewFeat("");
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      // Persist any provider keys the user entered (keychain in desktop, live in sidecar).
      for (const [prov, val] of Object.entries(keyValues)) {
        if (!val.trim() || !KEYABLE[prov]) continue;
        if (isTauri()) await setSecret(KEYABLE[prov].env, val.trim());
        await api.setProviderKeys({ [prov]: val.trim() } as Record<string, string>);
      }
      const cleanDetails = Object.fromEntries(
        Object.entries(details).filter(([, v]) => v && v.trim()),
      );
      const r = await api.createFullProject({
        name: name.trim(),
        description: description.trim(),
        deadline: deadline || null,
        features,
        details: cleanDetails,
      });
      onCreated(r.project);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  }

  const canNext =
    (step === 0 && name.trim().length > 0) ||
    (step === 1 && features.some((f) => f.enabled)) ||
    step === 2;

  const keyProviders = suggestedKeys.filter((k) => KEYABLE[k]);
  const otherKeys = suggestedKeys.filter((k) => !KEYABLE[k]);

  return (
    <div className="wizard-overlay">
      <div className="wizard">
        <div className="wizard-head">
          <h2>New project</h2>
          <button className="btn-ghost" onClick={onCancel}>✕</button>
        </div>

        <div className="wizard-steps">
          {STEPS.map((s, i) => (
            <div key={s} className={`wizard-step ${i === step ? "active" : ""} ${i < step ? "done" : ""}`}>
              <span className="wizard-step-num">{i < step ? "✓" : i + 1}</span>
              <span>{s}</span>
            </div>
          ))}
        </div>

        <div className="wizard-body">
          {error && <div className="error">{error}</div>}

          {step === 0 && (
            <>
              <label className="field-label">Project name</label>
              <input type="text" value={name} placeholder="My ambitious project"
                onChange={(e) => setName(e.target.value)} autoFocus />
              <label className="field-label" style={{ marginTop: 14 }}>Description</label>
              <textarea value={description} placeholder="What are you building, for whom, and why?"
                onChange={(e) => setDescription(e.target.value)} style={{ minHeight: 110 }} />
              <label className="field-label" style={{ marginTop: 14 }}>Deadline (optional)</label>
              <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)}
                style={{ maxWidth: 220 }} />
            </>
          )}

          {step === 1 && (
            <>
              <div className="task-add" style={{ marginBottom: 12 }}>
                <button onClick={() => void suggest()} disabled={busy}>
                  {busy ? "Thinking…" : features.length ? "Re-suggest features" : "Suggest features"}
                </button>
                <span className="hint">from your description — toggle, edit, or add your own.</span>
              </div>
              {features.length === 0 && (
                <p className="hint">No features yet. Use “Suggest features”, or add your own below.</p>
              )}
              {features.map((f, i) => (
                <div key={i} className={`bt-card ${f.enabled ? "" : "dismissed"}`}
                  style={{ borderLeftColor: f.enabled ? "var(--accent)" : "var(--faint)" }}>
                  <button className="status-dot" onClick={() => toggleFeature(i)}
                    title={f.enabled ? "included" : "excluded"}>{f.enabled ? "✓" : ""}</button>
                  <div className="bt-body">
                    <div className="bt-title">{f.name}</div>
                    {f.description && <div className="meta">{f.description}</div>}
                  </div>
                </div>
              ))}
              <div className="task-add" style={{ marginTop: 10 }}>
                <input type="text" value={newFeat} placeholder="Add a custom feature…"
                  onChange={(e) => setNewFeat(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") addFeature(); }} />
                <button onClick={addFeature}>Add</button>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <h3>API keys</h3>
              {keyProviders.length === 0 && otherKeys.length === 0 && (
                <p className="hint">No API keys look necessary for the chosen features. You can always
                  add keys later in Settings. Mock + local (Ollama) models need none.</p>
              )}
              {keyProviders.map((prov) => (
                <div key={prov} className="task-add">
                  <label style={{ flex: 1 }}>
                    {KEYABLE[prov].label} <span className="hint">— free key from {KEYABLE[prov].where}</span>
                    <input type="password" placeholder={`${KEYABLE[prov].env}…`}
                      value={keyValues[prov] ?? ""}
                      onChange={(e) => setKeyValues((v) => ({ ...v, [prov]: e.target.value }))} />
                  </label>
                </div>
              ))}
              {otherKeys.length > 0 && (
                <p className="hint">Also consider keys for: {otherKeys.join(", ")} (configure these in
                  their own dashboards).</p>
              )}
              {!isTauri() && keyProviders.length > 0 && (
                <p className="hint">Browser mode: keys apply to the running sidecar but aren’t saved to
                  the OS keychain.</p>
              )}

              <h3 style={{ marginTop: 18 }}>Project details</h3>
              {DETAIL_FIELDS.map((d) => (
                <div key={d.key} style={{ marginBottom: 10 }}>
                  <label className="field-label">{d.label}</label>
                  <input type="text" placeholder={d.placeholder} value={details[d.key] ?? ""}
                    onChange={(e) => setDetails((v) => ({ ...v, [d.key]: e.target.value }))}
                    style={{ width: "100%" }} />
                </div>
              ))}
            </>
          )}

          {step === 3 && (
            <div className="wizard-review">
              <div className="review-row"><span>Name</span><b>{name || "—"}</b></div>
              <div className="review-row"><span>Description</span><b>{description || "—"}</b></div>
              <div className="review-row"><span>Deadline</span><b>{deadline || "none"}</b></div>
              <div className="review-row"><span>Features</span>
                <b>{features.filter((f) => f.enabled).map((f) => f.name).join(", ") || "—"}</b></div>
              <div className="review-row"><span>Details</span>
                <b>{Object.entries(details).filter(([, v]) => v?.trim())
                  .map(([k, v]) => `${k}: ${v}`).join("; ") || "—"}</b></div>
              <p className="hint" style={{ marginTop: 12 }}>
                Creating this will make a folder under your workspace with a tailored prompt for every
                app feature and a JSON mirror of all project data (autosaved + cloud-backable).
              </p>
            </div>
          )}
        </div>

        <div className="wizard-foot">
          <button className="btn-ghost" onClick={() => (step === 0 ? onCancel() : setStep(step - 1))}>
            {step === 0 ? "Cancel" : "Back"}
          </button>
          {step < STEPS.length - 1 ? (
            <button onClick={() => setStep(step + 1)} disabled={!canNext}>Next</button>
          ) : (
            <button onClick={() => void create()} disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create project"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
