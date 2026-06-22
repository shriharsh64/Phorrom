// Thin client for the Phorrom sidecar. In dev the sidecar runs on localhost; once the Tauri
// shell exists it will inject the real base URL + bearer token. Configurable via Vite env.

const BASE = (import.meta.env.VITE_SIDECAR_URL as string) ?? "http://127.0.0.1:8008";

export interface Message {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ProviderInfo {
  provider: string;
  available: boolean;
  models: string[];
}

export interface ChatResult {
  text: string;
  provider: string;
  model: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string }>("/health"),
  providers: () => req<{ providers: ProviderInfo[] }>("/providers"),
  chat: (messages: Message[], provider: string, model: string) =>
    req<ChatResult>("/chat", {
      method: "POST",
      body: JSON.stringify({ messages, provider, model }),
    }),
};
