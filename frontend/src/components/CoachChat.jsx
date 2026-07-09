import { useState } from "react";
import { api } from "../api.js";

export default function CoachChat({ jobId, forceCareer = false }) {
  const [log, setLog] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  // "job" = grounded in just the currently-selected job (original behavior);
  // "career" = grounded in EVERY completed job on this account, with a
  // session-by-session progression block so the coach can actually answer
  // "have I improved" questions (see backend/career.py, POST /career/coach).
  // forceCareer (set when the header's Gameplay dropdown is on "All Gameplay
  // (Combined)" - see App.jsx's isCombined) means there's no single job to
  // ground "This job" scope in, so that toggle is hidden entirely and scope
  // always starts on "career".
  const [scope, setScope] = useState(forceCareer ? "career" : "job");

  async function send() {
    const question = input.trim();
    if (!question || sending) return;
    if (scope === "job" && !jobId) return;
    setLog((l) => [...l, { cls: "you", text: question }]);
    setInput("");
    setSending(true);
    try {
      const res = scope === "career" ? await api.askCareerCoach(question) : await api.askCoach(jobId, question);
      setLog((l) => [...l, { cls: "coach", text: res.answer }]);
    } catch (e) {
      setLog((l) => [...l, { cls: "error", text: `Coach unavailable: ${e.message}` }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="card">
      {!forceCareer && (
        <div className="tabs-inline small" style={{ marginBottom: 12 }}>
          <button className={`tab-inline ${scope === "job" ? "active" : ""}`} onClick={() => setScope("job")}>
            This job
          </button>
          <button className={`tab-inline ${scope === "career" ? "active" : ""}`} onClick={() => setScope("career")}>
            All-time (career)
          </button>
        </div>
      )}
      <div className="chat-log">
        {!log.length && (
          <div className="empty">
            {scope === "career"
              ? "Ask about your improvement across every session you've uploaded - e.g. \"have I gotten better at closing games?\""
              : "Ask about leads, matchups, or what to change next."}
          </div>
        )}
        {log.map((m, i) => (
          <div className={`msg ${m.cls}`} key={i}>{m.text}</div>
        ))}
        {sending && <div className="msg coach typing">Thinking…</div>}
      </div>
      <div className="chat-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder={scope === "career" ? "e.g. how has my closing rate changed over time?" : "e.g. what's my best lead and why?"}
        />
        <button onClick={send} disabled={sending}>Ask</button>
      </div>
    </div>
  );
}
