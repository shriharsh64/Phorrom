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

// --- Resource & Tooling Advisor (#3) ---------------------------------------

export interface ResourceRow {
  id: number;
  kind: string;
  name: string;
  stage: string | null;
  url: string | null;
  is_free: number;
  rationale: string | null;
  status: string;
}

export interface LearningRow {
  id: number;
  concept: string;
  title: string;
  url: string | null;
  source: string | null;
  rationale: string | null;
  prereq_order: number;
  is_gap: number;
  priority: number;
  status: string;
}

export interface BreakthroughRow {
  id: number;
  title: string;
  description: string | null;
  benefit_types: string[];
  impact: string;
  effort: string;
  rationale: string | null;
  related_concepts: string[];
  score: number;
  status: string;
}

export interface ConceptRow {
  id: number;
  name: string;
  status: "gap" | "learning" | "mastered";
  origin: string;
}

export interface AdvisorOverview {
  resources: ResourceRow[];
  learning: LearningRow[];
  concepts: ConceptRow[];
  breakthroughs: BreakthroughRow[];
  progress: {
    resources: { total: number; done: number };
    learning: { total: number; todo: number; in_progress: number; done: number; gaps: number };
    concepts: { gap: number; learning: number; mastered: number };
    breakthroughs: { total: number };
  };
}

export interface AdvisorContext {
  problem?: string;
  ideas?: string[];
  task_types?: string[];
  tech?: string[];
}

export const api = {
  health: () => req<{ status: string }>("/health"),
  providers: () => req<{ providers: ProviderInfo[] }>("/providers"),
  chat: (messages: Message[], provider: string, model: string) =>
    req<ChatResult>("/chat", {
      method: "POST",
      body: JSON.stringify({ messages, provider, model }),
    }),

  advisorRecommend: (project_id: number, context: AdvisorContext, provider = "mock", model = "mock-small") =>
    req<{ overview: AdvisorOverview }>("/advisor/recommend", {
      method: "POST",
      body: JSON.stringify({ project_id, context, provider, model }),
    }),
  advisorOverview: (project_id: number) =>
    req<AdvisorOverview>(`/advisor/overview?project_id=${project_id}`),
  setResourceStatus: (id: number, status: string) =>
    req(`/advisor/resources/${id}/status`, { method: "POST", body: JSON.stringify({ status }) }),
  setLearningStatus: (id: number, status: string) =>
    req<{ mastered: string[] }>(`/advisor/learning/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  setBreakthroughStatus: (id: number, status: string) =>
    req(`/advisor/breakthroughs/${id}/status`, { method: "POST", body: JSON.stringify({ status }) }),
};
