import { useState } from "react";
import { formatDuration } from "../lib/format.js";
import MatchSummary from "./MatchSummary.jsx";
import BattleReplay from "./BattleReplay.jsx";

export default function MatchesTable({ matches, events, jobId, onCorrected }) {
  const [expanded, setExpanded] = useState(null);
  // Shared across whichever match is currently expanded - only one match can
  // be open at a time (see `expanded` above), so one flag is enough.
  // "summary" (teams + plain recap + winner + any clarification questions,
  // via MatchSummary.jsx - the default landing view as of this redesign) |
  // "replay" (step-by-step battle reconstruction, unchanged).
  const [view, setView] = useState("summary");
  const incompleteCount = matches.filter((m) => !m.complete_data || m.winner === "unknown").length;
  const illegalCount = matches.filter((m) => (m.illegal_species_detected || []).length).length;

  return (
    <div className="card">
      <div className="matches-note-row">
        {incompleteCount > 0 && (
          <div className="note-banner warn">
            {incompleteCount} of {matches.length} matches marked ⚠ — either your team wasn't fully read
            (shouldn't happen) or no result screen was captured. Incomplete opponent data alone isn't
            flagged; their team-preview read can normally miss 1-2 of their 4.
          </div>
        )}
        {illegalCount > 0 && (
          <div className="note-banner bad">
            {illegalCount} match(es) marked 🚫 — a Pokémon that can't legally exist in this format was
            read (almost certainly a misidentification of a real, legal Pokémon).
          </div>
        )}
        {jobId && (
          <div className="note-banner">
            Click a match to see your team, the opponent's team, a turn-by-turn recap, and the result - if
            anything's worth double-checking, you'll get a short, targeted question with a photo instead of
            every event needing a look.
          </div>
        )}
      </div>
      <table>
        <thead>
          <tr>
            <th></th><th>#</th><th>Result</th><th>Your lead</th><th>Your brought</th>
            <th>Opponent brought</th><th>KOs landed / lost</th><th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {!matches.length && (
            <tr><td colSpan={8} className="empty">No matches yet.</td></tr>
          )}
          {matches.flatMap((m) => {
            const won = m.winner === "player";
            const lost = m.winner === "opponent";
            const resultCls = won ? "good" : lost ? "bad" : "warn";
            const resultText = won ? "Win" : lost ? "Loss" : "Unknown";
            const illegal = m.illegal_species_detected || [];
            let badge = null;
            if (illegal.length) badge = <span className="badge bad" title={`illegal: ${illegal.join(", ")}`}>🚫</span>;
            else if (!m.complete_data || m.winner === "unknown") badge = <span className="badge warn">⚠</span>;

            const isOpen = expanded === m.match;
            const rows = [
              <tr
                key={m.match}
                className="match-row-clickable"
                onClick={() => setExpanded(isOpen ? null : m.match)}
              >
                <td className="expand-arrow">{isOpen ? "▾" : "▸"}</td>
                <td>{m.match} {badge}</td>
                <td className={resultCls}>{resultText}</td>
                <td>{(m.player_lead || []).join(" + ") || "–"}</td>
                <td>{(m.player_brought || []).join(", ") || "–"}</td>
                <td>{(m.opponent_brought || []).join(", ") || "–"}</td>
                <td>{m.o_faints ?? 0} / {m.p_faints ?? 0}</td>
                <td>{formatDuration(m.duration_seconds)}</td>
              </tr>,
            ];
            if (isOpen) {
              rows.push(
                <tr key={`${m.match}-expanded`} className="match-row-expanded">
                  <td colSpan={8}>
                    <div className="tabs-inline small" style={{ marginBottom: 12 }}>
                      <button type="button" className={`tab-inline ${view === "summary" ? "active" : ""}`} onClick={() => setView("summary")}>
                        Summary
                      </button>
                      <button type="button" className={`tab-inline ${view === "replay" ? "active" : ""}`} onClick={() => setView("replay")}>
                        Battle replay
                      </button>
                    </div>
                    {view === "replay"
                      ? <BattleReplay jobId={jobId} events={events} matchNumber={m.match} />
                      : <MatchSummary jobId={jobId} events={events} matchNumber={m.match} onCorrected={onCorrected} />}
                  </td>
                </tr>,
              );
            }
            return rows;
          })}
        </tbody>
      </table>
    </div>
  );
}
