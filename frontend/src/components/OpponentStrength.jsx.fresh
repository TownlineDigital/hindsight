import { useState } from "react";
import { pctClass } from "../lib/format.js";

// Both sides' full 6-mon team preview for one match, brought-4 highlighted
// against the 2 that were left home. `brought` is the list actually used in
// battle (team_preview_evaluation's answer lookups are keyed by these names).
function RosterList({ team, brought }) {
  const broughtSet = new Set(brought || []);
  if (!team || !team.length) {
    return <span className="note">Not read for this match.</span>;
  }
  return (
    <ul className="roster-list">
      {team.map((name) => (
        <li key={name} className={broughtSet.has(name) ? "roster-brought" : "roster-left-home"}>
          {name}
          {!broughtSet.has(name) && <span className="note"> (left home)</span>}
        </li>
      ))}
    </ul>
  );
}

// Per-mon "who answers this" breakdown for one side of team_preview_evaluation
// - `answers` is {mon_name: [names of the other side's mons that threaten it]}.
function AnswerBreakdown({ title, answers }) {
  const entries = Object.entries(answers || {});
  if (!entries.length) return null;
  return (
    <div className="matchup-answer-col">
      <h4>{title}</h4>
      <ul className="matchup-answer-list">
        {entries.map(([mon, threats]) => (
          <li key={mon}>
            <strong>{mon}</strong>:{" "}
            {threats.length
              ? <span className="good">threatened by {threats.join(", ")}</span>
              : <span className="bad">no type answer found</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

const VERDICT_LABEL = { favorable: "Favorable", unfavorable: "Unfavorable", even: "Even" };
const VERDICT_PILL = { favorable: "pill-good", unfavorable: "pill-bad", even: "pill-warn" };

export default function OpponentStrength({ data }) {
  const c = data.correlation;
  const [expanded, setExpanded] = useState(null);

  return (
    <div className="opponent-strength">
      <p className="note">
        How much their brought 4 overlap on shared type weaknesses — a real doubles liability
        (one spread move or a well-picked attacker threatens multiple of their Pokémon at once).
        Lower risk score = tighter-built team. Correlated against your actual results below.
      </p>
      {c ? (
        <div className="overview-grid">
          <div className="card">
            <h3>Median risk score</h3>
            <div className="big">{c.median_risk_score}</div>
            <div className="note">{c.sample_size} matches scored</div>
          </div>
          <div className="card">
            <h3>Win rate vs weaker-built teams</h3>
            <div className={`big ${pctClass(c.win_rate_vs_weaker_built_teams)}`}>{c.win_rate_vs_weaker_built_teams}%</div>
            <div className="note">{c.vs_weaker_built_n} matches (above-median overlap)</div>
          </div>
          <div className="card">
            <h3>Win rate vs tighter-built teams</h3>
            <div className={`big ${pctClass(c.win_rate_vs_tighter_built_teams)}`}>{c.win_rate_vs_tighter_built_teams}%</div>
            <div className="note">{c.vs_tighter_built_n} matches (at/below-median overlap)</div>
          </div>
          <div className="card empty" style={{ gridColumn: "1 / -1" }}>{c.note}</div>
        </div>
      ) : (
        <div className="card empty">Not enough scored matches yet for a meaningful split.</div>
      )}

      <div className="note-banner" style={{ marginTop: 16 }}>
        The table below is <strong>Objective Team Preview Evaluation</strong> — "was this a strong
        bring given only what team preview showed," scored purely on typing (see each match's
        "type answers" detail), with zero knowledge of who actually won. It deliberately can't be
        biased by the result. For how the battle was actually <em>played</em> (move selection,
        positioning, predictions, resource management, adaptation), see the per-turn reports under
        Progression → Overall battle profile, and each match's Summary in the Matches tab.
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th></th><th>#</th><th>Matchup</th><th>Opponent brought</th>
              <th>Risk score</th><th>Shared weaknesses</th><th>Result</th>
            </tr>
          </thead>
          <tbody>
            {!data.matches.length && <tr><td colSpan={7} className="empty">No data</td></tr>}
            {data.matches.map((m) => {
              const shared = Object.entries(m.shared_weaknesses || {}).map(([t, n]) => `${t} (${n})`).join(", ") || "none";
              const coverageFull = m.coverage === `${(m.opponent_brought || []).length}/${(m.opponent_brought || []).length}`;
              const tpe = m.team_preview_evaluation || {};
              const isOpen = expanded === m.match;
              return (
                <tr key={m.match} className="match-row-clickable" onClick={() => setExpanded(isOpen ? null : m.match)}>
                  <td className="expand-arrow">{isOpen ? "▾" : "▸"}</td>
                  <td>{m.match}</td>
                  <td>
                    {tpe.verdict
                      ? <span className={`pill ${VERDICT_PILL[tpe.verdict] || ""}`}>{VERDICT_LABEL[tpe.verdict] || tpe.verdict}</span>
                      : <span className="note">–</span>}
                  </td>
                  <td>
                    {(m.opponent_brought || []).join(", ")}
                    {!coverageFull && <span className="note"> ({m.coverage} typed)</span>}
                  </td>
                  <td>{m.risk_score}</td>
                  <td>{shared}</td>
                  <td className={m.player_won ? "good" : "bad"}>{m.player_won ? "You won" : "You lost"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      </div>
      {(() => {
        // Expanded match-preview detail renders OUTSIDE .table-scroll
        // (added 2026-07-09, same reasoning as MatchesTable.jsx's own
        // comment) - its .two-col roster/answer grids have their own
        // mobile stacking (@media max-width: 800px) that works fine
        // regardless, but keeping it out of the horizontally-scrolling
        // table avoids extra empty space filling out the table's
        // min-width and keeps the detail panel's own width fully fluid.
        const m = data.matches.find((row) => row.match === expanded);
        if (!m) return null;
        const tpe = m.team_preview_evaluation || {};
        return (
          <div className="card matchup-detail" style={{ marginTop: 12 }}>
            <div className="two-col">
              <div>
                <h4>Your team preview (all 6)</h4>
                <RosterList team={m.player_team} brought={m.player_brought} />
              </div>
              <div>
                <h4>Opponent's team preview (all 6)</h4>
                <RosterList team={m.opponent_team} brought={m.opponent_brought} />
              </div>
            </div>
            <p className="note" style={{ marginTop: 10 }}>
              Type-only, brought-vs-brought (not the full preview) — see the note above
              the table for what this does and doesn't account for.
              {tpe.your_coverage && ` You had a type answer to ${tpe.your_coverage} of what they brought.`}
              {tpe.their_coverage && ` They had a type answer to ${tpe.their_coverage} of what you brought.`}
            </p>
            <div className="two-col" style={{ marginTop: 8 }}>
              <AnswerBreakdown title="Their brought 4 vs. your types" answers={tpe.your_type_answers} />
              <AnswerBreakdown title="Your brought 4 vs. their types" answers={tpe.their_type_answers} />
            </div>
          </div>
        );
      })()}
    </div>
  );
}
