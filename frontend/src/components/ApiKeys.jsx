import { useEffect, useState } from "react";
import { api } from "../api.js";

function formatDate(value) {
  if (value == null) return "never";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return isNaN(d.getTime()) ? "unknown" : d.toLocaleString();
}

/** Developer-facing "API keys" panel - long-lived credentials for external
 * clients (the planned Pokemon Showdown browser extension is the first
 * consumer) that can't hold a short-lived Supabase session. See
 * backend/api_keys.py's module docstring for the full design, especially
 * why the plaintext key is only ever shown here once, immediately after
 * creation, and never again after that. */
export default function ApiKeys() {
  const [keys, setKeys] = useState(null);
  const [error, setError] = useState(null);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState(null); // { key, id } - shown once
  const [copied, setCopied] = useState(false);

  async function reload() {
    try {
      const k = await api.listApiKeys();
      k.sort((a, b) => (b.created_at ? Date.parse(b.created_at) || b.created_at : 0)
                       - (a.created_at ? Date.parse(a.created_at) || a.created_at : 0));
      setKeys(k);
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
      const result = await api.createApiKey(label.trim() || null);
      setJustCreated(result);
      setCopied(false);
      setLabel("");
      await reload();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(keyId) {
    try {
      await api.revokeApiKey(keyId);
      if (justCreated && justCreated.id === keyId) setJustCreated(null);
      await reload();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleCopy() {
    if (!justCreated) return;
    try {
      await navigator.clipboard.writeText(justCreated.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API unavailable - the key text is still visible and
      // selectable in the banner itself, so this fails soft
    }
  }

  return (
    <div className="tab-panel">
      {error && <div className="banner">{error}</div>}

      <section>
        <div className="card">
          <h3>API keys</h3>
          <div className="note" style={{ marginBottom: 12 }}>
            Long-lived credentials for external clients that can't sign in through
            this dashboard directly - e.g. a browser extension that uploads
            Pokemon Showdown replays automatically after each match. Anyone who
            has a key can act as you against this API, so treat it like a
            password: paste it straight into the client that needs it, and
            revoke it immediately if it's ever exposed.
          </div>
          <form onSubmit={handleCreate} className="share-link-form">
            <label className="field small">
              <span>Label (e.g. "Showdown extension - laptop")</span>
              <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="optional" />
            </label>
            <button className="accent" type="submit" disabled={creating}>
              {creating ? "Generating…" : "Generate key"}
            </button>
          </form>
        </div>
      </section>

      {justCreated && (
        <section>
          <div className="note-banner">
            <strong>Copy this key now - it won't be shown again.</strong>
            <div className="api-key-reveal">
              <code>{justCreated.key}</code>
              <button type="button" onClick={handleCopy}>{copied ? "Copied!" : "Copy"}</button>
            </div>
          </div>
        </section>
      )}

      <section>
        <div className="card">
          <h3>Your API keys</h3>
          {keys === null && <div className="empty">Loading…</div>}
          {keys && !keys.length && <div className="empty">No API keys generated yet.</div>}
          {keys && keys.length > 0 && (
            <div className="mini-table">
              {keys.map((k) => {
                const active = !k.revoked_at;
                return (
                  <div className="share-link-row" key={k.id}>
                    <div className="share-link-main">
                      <span className={`pill ${active ? "pill-good" : "pill-bad"}`}>
                        {active ? "Active" : "Revoked"}
                      </span>
                      <span className="mini-label">{k.label || "(unlabeled)"}</span>
                      <span className="note">
                        {k.key_prefix}… · created {formatDate(k.created_at)}
                        {" · last used "}{formatDate(k.last_used_at)}
                      </span>
                    </div>
                    <div className="share-link-actions">
                      {active && (
                        <button type="button" onClick={() => handleRevoke(k.id)}>Revoke</button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
