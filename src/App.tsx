import { useEffect, useRef, useState } from "react";
import { api, type Message, type ProviderInfo } from "./lib/api";

interface Turn extends Message {
  meta?: string;
}

export default function App() {
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
        <div className="controls">
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
    </div>
  );
}
