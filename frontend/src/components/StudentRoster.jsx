import { useEffect, useState } from "react";
import { api } from "../api.js";
import SkillScores from "./SkillScores.jsx";
import CoachingFlags from "./CoachingFlags.jsx";
import { WinRateTable, CountTable } from "./StatTable.jsx";

function toRows(table) {
  return Object.entries(table || {})
    .map(([label, v]) => ({ label, wins: v.wins, total: v.total, winPct: v.win_pct }))
    .sort((a, b) => b.total - a.total);
}

function formatDate(value) {
  if (value == null) return "unknown";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return isNaN(d.getTime()) ? "unknown" : d.toLocaleDateString();
}

const NOTE_CATEGORIES = ["general", "coaching_plan", "skill_focus"];

function StudentDetail({ playerUserId, onBack, onRenamed }) {
  const [profile, setProfile] = useState(null);
  const [notes, setNotes] = useState(null);
  const [error, setError] = useState(null);
  const [noteText, setNoteText] = useState("");
  const [noteCategory, setNoteCategory] = useState("general");
  const [saving, setSaving] = useState(false);

  async function reload() {
    try {
      const [p, n] = await Promise.all([
        api.studentProfile(playerUserId), api.studentNotes(playerUserId),
      ]);
      setProfile(p);
      n.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      setNotes(n);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { reload(); }, [playerUserId]);

  async function handleAddNote(e) {
    e.preventDefault();
    if (!noteText.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.addStudentNote(playerUserId, noteText.trim(), noteCategory);
      setNoteText("");
      await reload();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteNote(noteId) {
    try {
      await api.deleteNote(noteId);
      await reload();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="tab-panel">
      <button type="button" onClick={onBack}>&larr; Back to students</button>
      {error && <div className="banner">{error}</div>}
      {!profile && <div className="empty">Loading…</div>}
      {profile && (
        <>
          <section>
            <div className="overview-grid">
              <div className="card hero-card">
                <div className="hero-side">
                  <div className="hero-big">{profile.record.wins}-{profile.record.losses}</div>
                  <div className="note">
                    {profile.record.matches} matches across {profile.sessions_count} upload session
                    {profile.sessions_count === 1 ? "" : "s"}
                  </div>
                </div>
              </div>
            </div>
          </section>
          <section>
            <h3>Skill scores (all-time)</h3>
            <SkillScores data={profile.skill_scores} />
          </section>
          <section>
            <h3>Coaching flags</h3>
            <CoachingFlags flags={profile.report.flags} />
          </section>
          <section>
            <div className="two-col">
              <WinRateTable title="Win rate by lead" rows={toRows(profile.record.by_lead)} />
              <WinRateTable title="Win rate by bring" rows={toRows(profile.record.by_bring)} />
            </div>
          </section>
          <section>
            <div className="two-col">
              <WinRateTable
                title="Toughest matchups"
                rows={(profile.report.toughest_matchups || []).map((m) => (
                  { label: m.pokemon, wins: m.wins, total: m.total, winPct: m.win_pct }))}
              />
              <CountTable
                title="Most used Pokémon"
                rows={(profile.report.most_used_pokemon || []).map(([label, count]) => ({ label, count }))}
              />
            </div>
          </section>

          <section>
            <div className="card">
              <h3>Your notes for this student</h3>
              <form onSubmit={handleAddNote} className="share-link-form">
                <label className="field small" style={{ flex: 1 }}>
                  <span>New note</span>
                  <input
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    placeholder="e.g. Focus on switch timing under Trick Room next session"
                  />
                </label>
                <label className="field small">
                  <span>Category</span>
                  <select value={noteCategory} onChange={(e) => setNoteCategory(e.target.value)}>
                    {NOTE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
                <button className="accent" type="submit" disabled={saving || !noteText.trim()}>
                  {saving ? "Saving…" : "Add note"}
                </button>
              </form>

              {notes === null && <div className="empty">Loading…</div>}
              {notes && !notes.length && <div className="empty">No notes yet - add one above.</div>}
              {notes && notes.length > 0 && (
                <div className="mini-table" style={{ marginTop: 12 }}>
                  {notes.map((n) => (
                    <div className="note-card" key={n.id}>
                      <div className="note-card-header">
                        {n.category && <span className="pill">{n.category}</span>}
                        <span className="note">{formatDate(n.created_at)}</span>
                        <button type="button" onClick={() => handleDeleteNote(n.id)}>Delete</button>
                      </div>
                      <div>{n.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

/** Coach-side "my students" roster: redeem a share link into a persistent
 * roster entry, rename/remove students, and open a student's aggregate
 * profile + notes. Anyone can act as a "coach" simply by redeeming a link -
 * there's no separate coach signup (see backend/coaching.py's docstring). */
export default function StudentRoster() {
  const [students, setStudents] = useState(null);
  const [error, setError] = useState(null);
  const [tokenInput, setTokenInput] = useState("");
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState(null);   // player_user_id, or null = roster list view
  const [renaming, setRenaming] = useState(null);   // player_user_id currently being renamed
  const [renameValue, setRenameValue] = useState("");

  async function reload() {
    try {
      const list = await api.listStudents();
      list.sort((a, b) => (b.added_at || 0) - (a.added_at || 0));
      setStudents(list);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { reload(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    let token = tokenInput.trim();
    if (!token) return;
    // accept either a bare token or a full pasted URL (…/coach/<token>)
    const m = token.match(/\/coach\/([^/?#]+)/);
    if (m) token = m[1];
    setAdding(true);
    setError(null);
    try {
      await api.addStudent(token);
      setTokenInput("");
      await reload();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(playerUserId) {
    try {
      await api.removeStudent(playerUserId);
      await reload();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleRename(playerUserId) {
    try {
      await api.renameStudent(playerUserId, renameValue.trim() || "Unnamed student");
      setRenaming(null);
      await reload();
    } catch (e) {
      setError(e.message);
    }
  }

  if (selected) {
    return <StudentDetail playerUserId={selected} onBack={() => setSelected(null)} />;
  }

  return (
    <div className="tab-panel">
      {error && <div className="banner">{error}</div>}

      <section>
        <div className="card">
          <h3>Add a student</h3>
          <div className="note" style={{ marginBottom: 12 }}>
            Paste a share link (or just its token) a player gave you.
          </div>
          <form onSubmit={handleAdd} className="share-link-form">
            <label className="field small" style={{ flex: 1 }}>
              <span>Share link or token</span>
              <input
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="https://…/coach/abc123… or just abc123…"
              />
            </label>
            <button className="accent" type="submit" disabled={adding || !tokenInput.trim()}>
              {adding ? "Adding…" : "Add student"}
            </button>
          </form>
        </div>
      </section>

      <section>
        <div className="card">
          <h3>Your students</h3>
          {students === null && <div className="empty">Loading…</div>}
          {students && !students.length && <div className="empty">No students yet - add one above.</div>}
          {students && students.length > 0 && (
            <div className="mini-table">
              {students.map((s) => (
                <div className="share-link-row" key={s.player_user_id}>
                  <div className="share-link-main">
                    {renaming === s.player_user_id ? (
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleRename(s.player_user_id)}
                      />
                    ) : (
                      <span className="mini-label">{s.coach_label}</span>
                    )}
                    <span className="note">added {formatDate(s.added_at)}</span>
                  </div>
                  <div className="share-link-actions">
                    <button type="button" onClick={() => setSelected(s.player_user_id)}>View profile</button>
                    {renaming === s.player_user_id ? (
                      <button type="button" onClick={() => handleRename(s.player_user_id)}>Save</button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => { setRenaming(s.player_user_id); setRenameValue(s.coach_label); }}
                      >
                        Rename
                      </button>
                    )}
                    <button type="button" onClick={() => handleRemove(s.player_user_id)}>Remove</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
