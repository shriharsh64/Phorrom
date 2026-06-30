import { useState } from "react";

interface Guide {
  icon: string;
  title: string;
  what: string;
  how: string[];
  best: string[];
}

const GUIDES: Guide[] = [
  {
    icon: "🚀", title: "Getting started",
    what: "Phorrom is your local-first AI project co-pilot. It understands a project, plans it, and helps you build it across many free AI models.",
    how: [
      "On first launch, pick a workspace folder — every project is saved as its own subfolder there.",
      "From the launcher, choose “New project” to describe your idea, or “Open existing” to resume one.",
      "Switch features using the sidebar; switch projects using the picker at the bottom of the sidebar.",
    ],
    best: [
      "Use one workspace folder you back up (e.g. inside Documents or a synced drive).",
      "Give a rich description up front — every feature’s prompt is generated from it.",
    ],
  },
  {
    icon: "✨", title: "Creating a project",
    what: "The new-project wizard collects a description, deadline, features, API keys and details, then scaffolds a folder and a tailored prompt for every feature.",
    how: [
      "Step 1 — Basics: name, description, optional deadline.",
      "Step 2 — Features: click “Suggest features” to get ideas from your description, toggle the ones you want, or add your own.",
      "Step 3 — Keys & details: paste any free API keys the features need, and add domain/audience/tech/constraints.",
      "Step 4 — Review and create. A folder appears in your workspace with prompts/ and exports/.",
    ],
    best: [
      "Keep features focused — enable a small core set first; you can add more later.",
      "API keys are optional: the mock provider and local Ollama models always work without keys.",
    ],
  },
  {
    icon: "🧾", title: "Feature prompts",
    what: "Auto-generated prompts, one per feature, each written the specific way that feature expects input. They live in the project’s prompts/ folder and in the Prompts tab.",
    how: [
      "Open the Prompts tab to read each prompt.",
      "Click “Copy” and paste it into the matching feature (e.g. the Plan prompt into Plan).",
      "Edit your project (re-run setup) and click “Regenerate” to refresh them.",
    ],
    best: ["Treat these as strong starting points — tweak wording for your exact intent before sending."],
  },
  {
    icon: "💬", title: "Chat",
    what: "A conversation with your project co-pilot. Pick any available provider/model; optionally turn on “optimize” for a self-evaluated, recalibrated answer.",
    how: [
      "Choose a provider and model in the top bar.",
      "Type a message; Enter sends, Shift+Enter makes a newline.",
      "Toggle “optimize” and a depth (brief/standard/deep) for higher-quality, scored replies.",
    ],
    best: [
      "Paste the generated Chat prompt first to give the model full project context.",
      "Use optimize → deep for important answers; it costs more tokens but self-checks relevance.",
    ],
  },
  {
    icon: "🗂️", title: "Plan (Problem-Statement Architect)",
    what: "Turns a rough description into a structured, scoped problem record: statement, gap, success criteria, constraints — plus a task list with priorities.",
    how: [
      "Paste a description (or the generated Plan prompt) and define the problem.",
      "Review the scoped record and answer any clarifying questions it surfaces.",
      "Add tasks; the prioritizer ranks them by urgency × impact and readiness.",
    ],
    best: ["Define the problem before ideating — every later feature reads this record."],
  },
  {
    icon: "💡", title: "Ideation",
    what: "Generates and ranks concepts by feasibility × novelty × relevance, and records the concepts each idea needs so the Advisor can target your gaps.",
    how: [
      "Optionally add a steer (or use the Ideation prompt), then generate.",
      "Review ranked ideas; mark ones you’ll pursue as selected.",
    ],
    best: ["Run ideation after the problem is defined so ideas stay relevant and scored well."],
  },
  {
    icon: "🔬", title: "Research (prior art)",
    what: "Searches real literature/patents and writes a grounded summary plus a “white-space” map of what’s unexplored. Summaries cite only retrieved results.",
    how: [
      "Enter a short query (or use the Research prompt) and run prior-art.",
      "Read the grounded summary and white-space; open sources via their links.",
    ],
    best: ["Keep queries short and specific; refine using terms from the first results."],
  },
  {
    icon: "🧩", title: "Orchestrator",
    what: "Decomposes one task into subtasks, routes each to the best free model, and allocates a token budget so heavy future work isn’t starved.",
    how: [
      "Enter a single concrete task (or the Orchestrator prompt) and a token budget.",
      "Review the subtask DAG, the per-model assignments, and the budget breakdown.",
      "Enable execute to actually run the routed subtasks.",
    ],
    best: ["Give one well-scoped task at a time; large vague tasks decompose poorly."],
  },
  {
    icon: "🧭", title: "Advisor",
    what: "Recommends free tools, libraries and datasets, builds a prerequisite-first learning plan for your skill gaps, and surfaces high-leverage breakthroughs.",
    how: [
      "Provide context (problem, ideas, task types, tech) or use the Advisor prompt and recommend.",
      "Work the learning plan top-down; mark items in-progress/done to update concept mastery.",
    ],
    best: ["Mark learning items done as you go — mastered concepts feed back into better ideation."],
  },
  {
    icon: "📄", title: "Docs",
    what: "Generates IEEE/ACM/APA reports from your real project data, and runs OCR / speech-to-text on media. Output lands in the project’s generated-docs/.",
    how: [
      "Pick a style and title (or use the Docs prompt) and generate.",
      "For OCR/transcription, point at a local image/audio file.",
    ],
    best: ["Generate docs after you have a problem record, tasks and research for richer reports."],
  },
  {
    icon: "📊", title: "Dashboard",
    what: "Shows provider health (circuit-breaker state), token usage by provider, and the learned token/quality estimators.",
    how: ["Open Dashboard to monitor availability and spend.", "Train the estimator once you have run history."],
    best: ["Check here if a provider seems unavailable — an open circuit means it’s temporarily skipped."],
  },
  {
    icon: "⚙️", title: "Settings, autosave & cloud backup",
    what: "Store provider API keys in the OS keychain, control autosave, and back up an encrypted snapshot to Google Drive.",
    how: [
      "Add provider keys in Settings; local/mock models need none.",
      "Autosave writes each project’s data to its folder on an interval (configurable in Settings).",
      "Connect Google, set a passphrase, and back up. With cloud autobackup on, snapshots upload automatically.",
    ],
    best: [
      "Use a passphrase you won’t forget — backups are encrypted on-device and can’t be restored without it.",
      "Keep autosave on so your folder always mirrors the latest state before a backup.",
    ],
  },
];

export default function HelpPanel() {
  const [open, setOpen] = useState<string | null>(GUIDES[0].title);
  return (
    <div className="advisor">
      <section>
        <h2>Help & guide</h2>
        <p className="hint" style={{ textAlign: "left", marginBottom: 16 }}>
          Every feature explained simply — what it does, how to use it, and the best way to get value
          from it. Click a card to expand.
        </p>
        {GUIDES.map((g) => {
          const isOpen = open === g.title;
          return (
            <div key={g.title} className="bt-card" style={{ flexDirection: "column", alignItems: "stretch", cursor: "pointer" }}
              onClick={() => setOpen(isOpen ? null : g.title)}>
              <div className="bt-title">
                <span><span style={{ marginRight: 8 }}>{g.icon}</span>{g.title}</span>
                <span className="bt-score">{isOpen ? "▲" : "▼"}</span>
              </div>
              {isOpen && (
                <div onClick={(e) => e.stopPropagation()} style={{ cursor: "default" }}>
                  <p className="meta" style={{ fontSize: 13.5 }}>{g.what}</p>
                  <h3 style={{ marginTop: 12 }}>How to use</h3>
                  <ol className="help-list">{g.how.map((h, i) => <li key={i}>{h}</li>)}</ol>
                  <h3 style={{ marginTop: 10 }}>Best practices</h3>
                  <ul className="help-list">{g.best.map((b, i) => <li key={i}>{b}</li>)}</ul>
                </div>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
