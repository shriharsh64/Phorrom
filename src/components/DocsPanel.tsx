import { useEffect, useState } from "react";
import FeatureBrief from "./FeatureBrief";
import { api, type DocResult, type MultimodalResult } from "../lib/api";

// Capability #5 (document generation) + multimodal extraction (OCR / speech-to-text).
export default function DocsPanel({ projectId }: { projectId: number }) {
  const [tools, setTools] = useState<Record<string, string | null>>({});
  const [format, setFormat] = useState("pdf");
  const [style, setStyle] = useState("ieee");
  const [doc, setDoc] = useState<DocResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [ocrPath, setOcrPath] = useState("");
  const [audioPath, setAudioPath] = useState("");
  const [mm, setMm] = useState<MultimodalResult | null>(null);

  useEffect(() => {
    api.toolsStatus().then(setTools).catch(() => void 0);
  }, []);

  async function generate() {
    setBusy(true); setErr(null); setDoc(null);
    try { setDoc(await api.generateDoc(projectId, format, style)); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }

  const tool = (k: string, label: string) => (
    <span className="tag" style={{ color: tools[k] ? "#56d364" : "#f85149" }}>
      {label}: {tools[k] ? "ready" : "missing"}
    </span>
  );

  return (
    <div className="advisor">
      <FeatureBrief projectId={projectId} feature="docs" />
      <section>
        <h2>Document &amp; research-paper generator</h2>
        <div className="progress-row" style={{ flexWrap: "wrap" }}>
          {tool("pandoc", "Pandoc")}{tool("latex_bin", "LaTeX")}
          {tool("tesseract", "Tesseract")}{tool("whisper", "whisper")}{tool("whisper_model", "model")}
        </div>
        <div className="task-add">
          <label>format
            <select value={format} onChange={(e) => setFormat(e.target.value)}>
              <option value="pdf">PDF</option><option value="docx">DOCX</option><option value="md">Markdown</option>
            </select>
          </label>
          <label>style
            <select value={style} onChange={(e) => setStyle(e.target.value)}>
              <option value="ieee">IEEE</option><option value="acm">ACM</option><option value="apa">APA</option>
            </select>
          </label>
          <button onClick={() => void generate()} disabled={busy}>{busy ? "Generating…" : "Generate report"}</button>
        </div>
        {err && <div className="error">{err}</div>}
        {doc && (
          <div className="bt-card" style={{ borderLeftColor: "#3fb950" }}>
            <div className="bt-body">
              <div className="bt-title">Generated {doc.format.toUpperCase()}<span className="bt-score">{doc.style.toUpperCase()}</span></div>
              <div className="meta">saved to: {doc.path}</div>
              {doc.warning && <div className="meta">⚠ {doc.warning}</div>}
              <pre className="doc-preview">{doc.markdown.slice(0, 1200)}{doc.markdown.length > 1200 ? "\n…" : ""}</pre>
            </div>
          </div>
        )}
      </section>

      <section style={{ marginTop: 18 }}>
        <h2>Multimodal input</h2>
        <div className="task-add">
          <input placeholder="image path for OCR (png/jpg/pdf)…" value={ocrPath} onChange={(e) => setOcrPath(e.target.value)} />
          <button onClick={async () => setMm(await api.ocr(ocrPath))} disabled={!ocrPath}>OCR</button>
        </div>
        <div className="task-add">
          <input placeholder="audio path to transcribe (16kHz wav)…" value={audioPath} onChange={(e) => setAudioPath(e.target.value)} />
          <button onClick={async () => setMm(await api.transcribe(audioPath))} disabled={!audioPath}>Transcribe</button>
        </div>
        {mm && (
          <div className="bt-card" style={{ borderLeftColor: mm.ok ? "#3fb950" : "#f85149" }}>
            <div className="bt-body">
              {mm.ok ? <pre className="doc-preview">{mm.text || "(empty)"}</pre> : <div className="meta">⚠ {mm.error}</div>}
              {mm.engine && <div className="meta">via {mm.engine}{mm.model ? ` (${mm.model})` : ""}</div>}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
