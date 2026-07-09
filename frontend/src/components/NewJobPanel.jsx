import { useRef, useState } from "react";
import { api } from "../api.js";

const SOURCE_TABS = [
  { id: "url", label: "Video URL" },
  { id: "upload", label: "Video upload" },
  { id: "showdown", label: "Showdown replay" },
];

// Mode (singles/doubles - see adapters/pokemon/{singles,doubles}.json) and
// regulation (which Pokemon Champions roster/mechanics are legal right now -
// see adapters/pokemon/regulations/<id>.json and ARCHITECTURE_HANDOFF.md
// section 3a) are independent axes: mode almost never changes, regulation
// rotates every couple months. Defaults match the backend's own defaults
// (doubles / m-b, the current regulation) so leaving these untouched keeps
// working exactly like before this feature existed.
const MODES = [
  { id: "doubles", label: "Doubles" },
  { id: "singles", label: "Singles" },
];
const REGULATIONS = [
  { id: "m-b", label: "Regulation M-B (current)" },
  { id: "m-a", label: "Regulation M-A (launch, superseded)" },
];

// A drag-and-drop file zone, plain HTML5 drag events (no extra dependency) -
// works for both the single video file and the multi-file Showdown replay
// case, just with `multiple` toggled. Clicking it falls back to a normal
// file picker for anyone who'd rather not drag anything.
function DropZone({ accept, multiple, files, onFiles, hint }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  function handleFiles(fileList) {
    const arr = Array.from(fileList || []);
    onFiles(multiple ? arr : arr.slice(0, 1));
  }

  return (
    <div
      className={`dropzone ${dragging ? "dragging" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handleFiles(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
      role="button" tabIndex={0}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        style={{ display: "none" }}
        onChange={(e) => handleFiles(e.target.files)}
      />
      {!files.length && <p className="dropzone-hint">{hint}</p>}
      {!!files.length && (
        <ul className="dropzone-files">
          {files.map((f, i) => <li key={`${f.name}-${i}`}>{f.name}</li>)}
        </ul>
      )}
    </div>
  );
}

export default function NewJobPanel({ onClose, onJobCreated }) {
  const [tab, setTab] = useState("url");
  const [mode, setMode] = useState("doubles");
  const [regulation, setRegulation] = useState("m-b");
  const [url, setUrl] = useState("");
  const [videoFile, setVideoFile] = useState([]);
  const [replayMode, setReplayMode] = useState("files"); // "files" | "urls"
  const [replayFiles, setReplayFiles] = useState([]);
  const [replayUrlsText, setReplayUrlsText] = useState("");
  const [player, setPlayer] = useState("p1");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);

    const formData = new FormData();
    formData.append("game", "pokemon");
    formData.append("mode", mode);
    formData.append("regulation", regulation);

    if (tab === "url") {
      if (!url.trim()) { setError("Enter a video URL."); return; }
      formData.append("source_type", "url");
      formData.append("url", url.trim());
    } else if (tab === "upload") {
      if (!videoFile.length) { setError("Choose or drop a video file."); return; }
      formData.append("source_type", "upload");
      formData.append("file", videoFile[0]);
    } else {
      formData.append("source_type", "showdown");
      formData.append("player", player.trim() || "p1");
      if (replayMode === "files") {
        if (!replayFiles.length) { setError("Choose or drop at least one replay file."); return; }
        replayFiles.forEach((f) => formData.append("files", f));
      } else {
        const urls = replayUrlsText.split("\n").map((s) => s.trim()).filter(Boolean);
        if (!urls.length) { setError("Paste at least one replay URL."); return; }
        urls.forEach((u) => formData.append("urls", u));
      }
    }

    setSubmitting(true);
    try {
      const job = await api.createJob(formData);
      onJobCreated(job.job_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>New job</h3>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="tabs-inline">
          {SOURCE_TABS.map((t) => (
            <button
              type="button" key={t.id}
              className={`tab-inline ${tab === t.id ? "active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error && <div className="banner">{error}</div>}

        <form onSubmit={submit} className="new-job-form">
          <div className="two-col">
            <label className="field">
              <span>Mode</span>
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Regulation</span>
              <select value={regulation} onChange={(e) => setRegulation(e.target.value)}>
                {REGULATIONS.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
              </select>
            </label>
          </div>

          {tab === "url" && (
            <label className="field">
              <span>Video URL</span>
              <input
                type="url" value={url} onChange={(e) => setUrl(e.target.value)}
                placeholder="https://twitch.tv/videos/... or a YouTube link"
              />
            </label>
          )}

          {tab === "upload" && (
            <DropZone
              accept="video/*"
              multiple={false}
              files={videoFile}
              onFiles={setVideoFile}
              hint="Drag and drop a video file here, or click to choose one"
            />
          )}

          {tab === "showdown" && (
            <>
              <div className="tabs-inline small">
                <button
                  type="button" className={`tab-inline ${replayMode === "files" ? "active" : ""}`}
                  onClick={() => setReplayMode("files")}
                >
                  Upload files
                </button>
                <button
                  type="button" className={`tab-inline ${replayMode === "urls" ? "active" : ""}`}
                  onClick={() => setReplayMode("urls")}
                >
                  Paste URLs
                </button>
              </div>

              {replayMode === "files" ? (
                <DropZone
                  accept=".html,.json"
                  multiple={true}
                  files={replayFiles}
                  onFiles={setReplayFiles}
                  hint="Drag and drop one or more saved replay .html/.json files here (combined as consecutive matches), or click to choose"
                />
              ) : (
                <label className="field">
                  <span>Replay URLs (one per line)</span>
                  <textarea
                    rows={4} value={replayUrlsText} onChange={(e) => setReplayUrlsText(e.target.value)}
                    placeholder={"https://replay.pokemonshowdown.com/...\nhttps://replay.pokemonshowdown.com/..."}
                  />
                </label>
              )}

              <label className="field">
                <span>Which side is "you"?</span>
                <input
                  value={player} onChange={(e) => setPlayer(e.target.value)}
                  placeholder="Showdown username, or p1/p2"
                />
              </label>
            </>
          )}

          <div className="new-job-actions">
            <button type="button" onClick={onClose} disabled={submitting}>Cancel</button>
            <button type="submit" disabled={submitting}>{submitting ? "Starting…" : "Start job"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
