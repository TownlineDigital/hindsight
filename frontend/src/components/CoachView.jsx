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

/** The PUBLIC, unauthenticated view rendered at /coach/:token (see
 * main.jsx - this is a separate lightweight "page," not part of the signed-
 * in <App/> shell at all, since a coach viewing this link has no account
 * requirement). Fetches GET /coach-view/{token} with no Authorization
 * header required (see backend/coaching.py's module docstring for the full
 * privacy model: this is the ONE unauthenticated read path the whole
 * backend exposes, and it's deliberately narrow - aggregate stats for
 * exactly one player, nothing else). */
export default function CoachView({ token }) {
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.coachView(token).then(setProfile).catch((e) => setError(e.message));
  }, [token]);

  if (error) {
    return (
      <div className="app">
        <main>
          <div className="banner">
            This link is invalid, has been revoked, or has expired. ({error})
          </div>
        </main>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="app">
        <main><div className="banner info">Loading…</div></main>
      </div>
    );
  }

  return (
    <div className="app">
      <header>
        <div className="header-top">
          <div className="brand">
            <h1>VGC Coach</h1>
            <span className="sub">
              Shared performance profile{profile.shared_label ? ` — ${profile.shared_label}` : ""}
            </span>
          </div>
        </div>
      </header>
      <main>
        <div className="tab-panel">
          <div className="banner info">
            You're viewing a read-only, aggregate-only profile shared via a
            private link - no raw match video or per-match timeline is
            included.
          </div>

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
        </div>
      </main>
    </div>
  );
}
