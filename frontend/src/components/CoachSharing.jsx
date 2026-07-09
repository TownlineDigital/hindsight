import { useEffect, useState } from "react";
import { api } from "../api.js";

const EXPIRY_OPTIONS = [
  { value: "", label: "Never (revoke manually)" },
  { value: "7", label: "Expires in 7 days" },
  { value: "30", label: "Expires in 30 days" },
  { value: "90", label: "Expires in 90 days" },
];

function linkStatus(link) {
  if (link.revoked_at) return { text: "Revoked", cls: "bad" };
  if (link.expires_at && link.expires_at * 1000 < Date.now()) return { text: "Expired", cls: "warn" };
  return { text: "Active", cls: "good" };
}

function formatDate(value) {
  if (value == null) return "never";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return isNaN(d.getTime()) ? "unknown" : d.toLocaleDateString();
}

/** Player-side "share with a coach" panel: generate a link (this player's
 * own choice of label + expiry, per the "give the player the option"
 * decision), manage existing links, and read notes any coach has left -
 * see backend/coaching.py's module docstring for the full privacy model
 * this UI is built around (nothing is visible to anyone without a link this
 * player themselves generated). */
export default function CoachSharing() {
  const [links, setLinks] = useState(null);
  const [notes, setNotes] = useState(null);
  const [error, setError] = useState(null);
  const [label, setLabel] = useState("");
  const [expiry, setExpiry] = useState("");
  const [creating, setCreating] = useState(false);
  const [copiedToken, setCopiedToken] = useState(null);

  async function reload() {
    try {
      const [l, n] = await Promise.all([api.listShareLinks(), api.myCoachingNotes()]);
      l.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      n.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      setLinks(l);
      setNotes(n);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { reload(); }, []);

  async function handleCreate(e) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await api.createShareLink(label.trim() || null, expiry ? Number(expiry) : null);
      setLabel("");
      setExpiry("");
      await reload();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(token) {
    try {
      await api.revokeShareLink(token);
      await reload();
    } catch (e) {
      setError(e.message);
    }
  }

  function shareUrl(token) {
    // BASE_URL is "/dashboard/" in the real production build (see
    // vite.config.js's `base`, matching backend/main.py's StaticFiles
    // mount) and "/" in plain dev - building the link off it (rather than
    // hardcoding either) means the generated URL actually resolves
    // regardless of which mode generated it.
    const base = import.meta.env.BASE_URL.endsWith("/")
      ? import.meta.env.BASE_URL
      : import.meta.env.BASE_URL + "/";
    return `${window.location.origin}${base}coach/${token}`;
  }

  async function handleCopy(token) {
    try {
      await navigator.clipboard.writeText(shareUrl(token));
      setCopiedToken(token);
      setTimeout(() => setCopiedToken((t) => (t === token ? null : t)), 1500);
    } catch {
      // clipboard API unavailable (e.g. no HTTPS/permission) - the link text
      // is still visible in the row itself, so this fails soft
    }
  }

  return (
    <div className="tab-panel">
      {error && <div className="banner">{error}</div>}

      <section>
        <div className="card">
          <h3>Share your stats with a coach</h3>
          <div className="note" style={{ marginBottom: 12 }}>
            Anyone with this link can see your aggregate performance profile
            (skill scores, coaching flags, toughest matchups) - never your raw
            match video or per-match timeline. Your account stays completely
            private otherwise; nothing here is ever searchable or listed
            anywhere.
          </div>
          <form onSubmit={handleCreate} className="share-link-form">
            <label className="field small">
              <span>Label (private note to yourself, e.g. "Coach Sarah")</span>
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="optional" />
            </label>
            <label className="field small">
              <span>Link lifetime</span>
              <select value={expiry} onChange={(e) => setExpiry(e.target.value)}>
                {EXPIRY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            <button className="accent" type="submit" disabled={creating}>
              {creating ? "Generating…" : "Generate link"}
            </button>
          </form>
        </div>
      </section>

      <section>
        <div className="card">
          <h3>Your share links</h3>
          {links === null && <div className="empty">Loading…</div>}
          {links && !links.length && <div className="empty">No links generated yet.</div>}
          {links && links.length > 0 && (
            <div className="mini-table">
              {links.map((l) => {
                const status = linkStatus(l);
                const active = status.text === "Active";
                return (
                  <div className="share-link-row" key={l.token}>
                    <div className="share-link-main">
                      <span className={`pill pill-${status.cls}`}>{status.text}</span>
                      <span className="mini-label">{l.label || "(unlabeled)"}</span>
                      <span className="note">
                        created {formatDate(l.created_at)}
                        {l.expires_at ? ` · expires ${formatDate(l.expires_at)}` : ""}
                        {" · last viewed "}{formatDate(l.last_viewed_at)}
                      </span>
                    </div>
                    <div className="share-link-actions">
                      {active && (
                        <button type="button" onClick={() => handleCopy(l.token)}>
                          {copiedToken === l.token ? "Copied!" : "Copy link"}
                        </button>
                      )}
                      {active && (
                        <button type="button" onClick={() => handleRevoke(l.token)}>Revoke</button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>

      <section>
        <div className="card">
          <h3>Coaching notes</h3>
          <div className="note" style={{ marginBottom: 12 }}>
            Anything a coach has left for you, across every coach who's added
            you to their roster - read-only here.
          </div>
          {notes === null && <div className="empty">Loading…</div>}
          {notes && !notes.length && <div className="empty">No coaching notes yet.</div>}
          {notes && notes.length > 0 && (
            <div className="mini-table">
              {notes.map((n) => (
                <div className="note-card" key={n.id}>
                  <div className="note-card-header">
                    <span className="mini-label">{n.coach_email || "A coach"}</span>
                    {n.category && <span className="pill">{n.category}</span>}
                    <span className="note">{formatDate(n.created_at)}</span>
                  </div>
                  <div>{n.text}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
