import { useState } from "react";
import { Ring, MultiTrendLine } from "../lib/charts.jsx";
import { WinRateTable, CountTable } from "./StatTable.jsx";
import { pctClass, scoreClass } from "../lib/format.js";

const SCORE_SERIES = [
  { key: "overall", label: "Overall", colorVar: "--accent" },
  { key: "tempo", label: "Tempo", colorVar: "--good" },
  { key: "adaptability", label: "Adaptability", colorVar: "--warn" },
  { key: "execution", label: "Execution", colorVar: "--bad" },
  { key: "closing", label: "Closing", colorVar: "--muted" },
];

function toRows(table) {
  return Object.entries(table || {})
    .map(([label, v]) => ({ label, wins: v.wins, total: v.total, winPct: v.win_pct }))
    .sort((a, b) => b.total - a.total);
}

function formatSessionDate(value) {
  if (value == null) return "unknown date";
  // created_at is a unix-epoch float in local dev mode, an ISO-8601 string
  // from real Supabase - same dual-shape problem backend/career.py's
  // _created_at_key handles on the sorting side (see that module's docstring).
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return isNaN(d.getTime()) ? "unknown date" : d.toLocaleDateString();
}

/** "Career" = every completed job this account has ever uploaded, merged
 * into one chronological history (see backend/career.py) - this is the
 * "track how the player has improved" view, distinct from the per-job
 * Overview/Progression tabs which only ever see one upload at a time. */
export default function CareerProgress({ data }) {
  const [scoreView, setScoreView] = useState("per_session"); // "per_session" | "cumulative"

  if (!data) return <div className="card empty">Loading career data…</div>;
  const { record, report, skillScores, trend } = data;

  const sessionsWithScores = (trend || []).filter((t) => t[scoreView] != null);
  const series = SCORE_SERIES.map((s) => ({
    label: s.label,
    colorVar: s.colorVar,
    points: (trend || []).map((t) => (t[scoreView] ? t[scoreView].scores?.[s.key] ?? (s.key === "overall" ? t[scoreView].overall : null) : null)),
  }));
  // "overall" isn't nested under .scores the way the 4 sub-scores are (see
  // skill_scores.compute_skill_scores' return shape) - the map above already
  // special-cases it, this just keeps the intent explicit for a reader.
  const xLabels = (trend || []).map((t) => `S${t.session}`);

  const winRateClass = pctClass(record.win_rate);

  return (
    <div className="tab-panel">
      <section>
        <div className="overview-grid">
          <div className="card hero-card">
            <Ring value={record.win_rate} colorVar={`--${winRateClass || "accent"}`} label="All-time win rate" />
            <div className="hero-side">
              <div className="hero-big">{record.wins}-{record.losses}</div>
              <div className="note">
                {record.matches} matches across {(trend || []).length} upload session{(trend || []).length === 1 ? "" : "s"}
              </div>
            </div>
          </div>
          <div className="card hero-card">
            <Ring
              value={skillScores?.overall}
              colorVar={`--${scoreClass(skillScores?.overall) || "accent"}`}
              label="All-time skill score"
              size={112}
            />
            <div className="hero-side">
              <div className="pill">{skillScores?.confidence?.tier || "No data yet"}</div>
              <div className="note">{skillScores?.matches_analyzed || 0} matches analyzed, all-time</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div className="card">
          <h3>Skill score trend across sessions</h3>
          <div className="tabs-inline small" style={{ marginBottom: 12 }}>
            <button
              className={`tab-inline ${scoreView === "per_session" ? "active" : ""}`}
              onClick={() => setScoreView("per_session")}
            >
              Per-session (real trend)
            </button>
            <button
              className={`tab-inline ${scoreView === "cumulative" ? "active" : ""}`}
              onClick={() => setScoreView("cumulative")}
            >
              Cumulative (all-time-so-far)
            </button>
          </div>
          <MultiTrendLine series={series} xLabels={xLabels} />
          <div className="note" style={{ marginTop: 8 }}>
            {scoreView === "per_session"
              ? "Each point is scored using ONLY that session's own matches - the clearest signal for whether you're actually improving, though early sessions with few matches will be noisier."
              : "Each point is scored using every match up through that session - smoother, but a recent improvement gets diluted by everything that came before it."}
          </div>
        </div>
      </section>

      <section>
        <div className="card">
          <h3>Upload sessions</h3>
          {!(trend || []).length ? (
            <div className="empty">No completed jobs yet.</div>
          ) : (
            <div className="mini-table">
              {trend.map((t) => (
                <div className="mini-row" key={t.session}>
                  <span className="mini-label">
                    Session {t.session} — {formatSessionDate(t.created_at)} ({t.matches_in_session} matches)
                  </span>
                  <span className={`mini-pct ${scoreClass(t.per_session?.overall)}`}>
                    {t.per_session?.overall != null ? `${t.per_session.overall} overall` : "not enough matches yet"}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="session-table-note">Oldest to newest, top to bottom.</div>
        </div>
      </section>

      <section>
        <div className="two-col">
          <WinRateTable title="All-time win rate by lead" rows={toRows(record.by_lead)} />
          <WinRateTable title="All-time win rate by bring" rows={toRows(record.by_bring)} />
        </div>
      </section>

      <section>
        <div className="two-col">
          <WinRateTable
            title="Toughest matchups, all-time"
            rows={(report?.toughest_matchups || []).map((m) => ({ label: m.pokemon, wins: m.wins, total: m.total, winPct: m.win_pct }))}
          />
          <CountTable
            title="Most used Pokémon, all-time"
            rows={(report?.most_used_pokemon || []).map(([label, count]) => ({ label, count }))}
          />
        </div>
      </section>
    </div>
  );
}
