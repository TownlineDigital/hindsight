import { useState } from "react";
import { formatDuration } from "../lib/format.js";
import MatchSummary from "./MatchSummary.jsx";
import BattleReplay from "./BattleReplay.jsx";

// In the combined "All Gameplay" view, `events` is career.merge_user_events'
// merged array - every match in it still carries the `source_job_id` of
// whichever original job it actually came from (a merged match is always
// entirely from one job; matches are never split across jobs). Frame-serving
// (GET /jobs/{id}/frame/...) and reference_frame paths are stored relative to
// that ORIGINAL job's own folder, so to show photos for a given match we have
// to route back to its real job_id, not the "__all__" sentinel - this looks
// up the first event for a match and reads its source_job_id back out.
function sourceJobIdFor(events, matchNumber) {
  const e = (events || []).find((ev) => ev.match === matchNumber);
  return e?.source_job_id || null;
}

export default function MatchesTable({ matches, events, jobId, isCombined, onCorrected }) {
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
        {jobId && !isCombined && (
          <div className="note-banner">
            Click a match to see your team, the opponent's team, a turn-by-turn recap, and the result - if
            anything's worth double-checking, you'll get a short, targeted question with a photo instead of
            every event needing a look.
          </div>
        )}
        {jobId && isCombined && (
          <div className="note-banner">
            Showing matches combined across every Gameplay upload. Click a match to see your team, the
            opponent's team, a turn-by-turn recap, and the result. Corrections aren't available in this
            combined view - open the match's original Gameplay upload from the dropdown above to fix
            anything.
          </div>
        )}
      </div>
      <div className="table-scroll">
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
            const row = (
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
              </tr>
            );

            // Expanded detail renders as a colSpan row directly under the
            // clicked match (reverted 2026-07-09, direct user request:
            // "instead of the card popping up at the bottom of each page,
            // can we have the card expand to show the result underneath
            // the match you are selecting?"). This briefly lived as a
            // standalone card below the whole table instead, specifically
            // to avoid squeezing MatchSummary/BattleReplay's own two-col
            // layouts into the table's horizontally-scrolling min-width:
            // 640px box on mobile - but since the summary row's 8 columns
            // already force that same horizontal scroll on any screen
            // under 640px, embedding the detail here doesn't introduce a
            // NEW scrolling requirement: the detail's own @media(max-width:
            // 800px) breakpoint (see styles.css .two-col) still stacks to
            // single column based on the real viewport width, so on a
            // phone it renders narrow and fits comfortably inside the
            // already-open 640px scroll area rather than forcing it wider.
            if (!isOpen) return [row];
            const matchJobId = isCombined ? sourceJobIdFor(events, m.match) : jobId;
            return [
              row,
              <tr key={`${m.match}-detail`} className="match-detail-row">
                <td colSpan={8} className="match-detail-cell">
                  <div className="match-detail-panel">
                    <div className="tabs-inline small" style={{ marginBottom: 12 }}>
                      <button type="button" className={`tab-inline ${view === "summary" ? "active" : ""}`} onClick={() => setView("summary")}>
                        Summary
                      </button>
                      <button type="button" className={`tab-inline ${view === "replay" ? "active" : ""}`} onClick={() => setView("replay")}>
                        Battle replay
                      </button>
                    </div>
                    {view === "replay"
                      ? <BattleReplay jobId={matchJobId} events={events} matchNumber={m.match} />
                      : <MatchSummary jobId={matchJobId} events={events} matchNumber={m.match} isCombined={isCombined} onCorrected={onCorrected} />}
                  </div>
                </td>
              </tr>,
            ];
          })}
        </tbody>
      </table>
      </div>
    </div>
  );
}
