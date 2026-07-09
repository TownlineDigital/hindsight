import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { namesOf, buildBattleTimeline } from "../lib/battleTimeline.js";
import {
  buildClarificationQueue, buildWinnerClarification, buildGenericClarifications, frameContextFor,
} from "../lib/clarifications.js";
import { ClarificationCard } from "./ClarificationQueue.jsx";
import MatchEvents, { EventThumb, ImageLightbox } from "./MatchEvents.jsx";

// Event types worth a line in the plain-English recap. Deliberately a
// whitelist, not "every event" - hp_change is too granular on its own (the
// pokemon_fainted/move_used lines already carry the moment that matters),
// and field_state without any weather/terrain/Trick Room/tailwind/screens
// text is just "who's active now," which the team panels above already show
// - see battleTimeline.js's captionFor for what each caption actually says.
const RECAP_EVENT_TYPES = new Set([
  "team_preview", "pokemon_sent_out", "move_used", "pokemon_fainted",
  "status_inflicted", "terastallized", "item_or_ability_activated", "battle_end",
]);

/** One compact hover tooltip string for a turn's battle-intelligence report -
 * every sub-report's own factors, concatenated, so a coach can see the full
 * "why" behind the one-line summary without cluttering the recap itself.
 * Skips a sub-report's factors when they're just the "nothing to report"
 * placeholder text (compute_speed_control/compute_threat_pressure's own
 * "No ... factors this turn" defaults - not worth repeating three times). */
function turnIntelTooltip(report) {
  const parts = [];
  for (const section of [report.speed_control, report.threat_pressure]) {
    for (const f of section.factors) {
      if (!f.startsWith("No ")) parts.push(f);
    }
  }
  for (const f of report.resource_advantage.factors) parts.push(f);
  return parts.join(" · ");
}

/** "Who won this match?" - the one clarification type that ISN'T about a
 * single event's field, but about the whole match's own headline result.
 * See lib/clarifications.js's buildWinnerClarification for why this can
 * happen at all (a real stream disruption right at the match boundary can
 * leave NO result screen in any frame either the vision model or the OCR
 * tier searched - not a case retrying the AI would ever fix). Resolving
 * applies the chosen winner to every battle_end event this match has (there
 * can be two - see that function's own docstring) in one go. */
function WinnerCard({ jobId, winnerInfo, onResolved }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [enlargedSrc, setEnlargedSrc] = useState(null);

  async function resolve(winner) {
    setSaving(true);
    setError(null);
    try {
      await Promise.all(
        winnerInfo.eventIndices.map((idx) => api.correctEvent(jobId, idx, { winner, confidence: 1.0 })),
      );
      onResolved();
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  }

  return (
    <div className="clarify-card">
      {winnerInfo.referenceFrame
        ? <EventThumb jobId={jobId} framePath={winnerInfo.referenceFrame} onEnlarge={setEnlargedSrc} />
        : <div className="event-thumb missing clarify-no-photo" title="No photo was captured near the end of this match">no photo</div>}
      <div className="clarify-body">
        <div className="clarify-question">Who won this match?</div>
        {winnerInfo.isNearestFallback ? (
          <div className="clarify-photo-note">
            No result screen was captured for this match - often a stream disconnect or a "be right back"
            screen right at the end. Showing the closest available photo
            {typeof winnerInfo.referenceFrameTimestamp === "number"
              ? ` (${winnerInfo.referenceFrameTimestamp.toFixed(1)}s into the match)` : ""} instead - it may be
            from shortly before the actual result.
          </div>
        ) : (
          <div className="clarify-photo-note">No photo at all was captured anywhere in this match.</div>
        )}
        {winnerInfo.referenceFrameShowsSubject === false && (
          <div className="clarify-photo-note visibility-warning">
            This photo may not clearly show the result screen - the camera may have been pointed elsewhere at
            that moment.
          </div>
        )}
        {error && <div className="banner">{error}</div>}
        <div className="clarify-actions">
          <button type="button" className="clarify-yes" disabled={saving} onClick={() => resolve("player")}>
            ✓ You won
          </button>
          <button type="button" className="clarify-alt" disabled={saving} onClick={() => resolve("opponent")}>
            Opponent won
          </button>
        </div>
      </div>
      {enlargedSrc && <ImageLightbox src={enlargedSrc} onClose={() => setEnlargedSrc(null)} />}
    </div>
  );
}

/** "What occurred here?" - the generic counterpart to the species-identity
 * card, for a flagged event that isn't shaped like a single-Pokemon guess
 * (see lib/clarifications.js's buildGenericClarifications). No structured
 * candidate buttons here - unlike a species mix-up, there's no short list
 * of likely alternatives to offer, so this is confirm-as-is or describe what
 * actually happened in free text. Resolving either way marks the event
 * confident (and clears roster_conflict) so it doesn't reappear next render. */
function GenericOccurrenceCard({ jobId, item, onResolved }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [enlargedSrc, setEnlargedSrc] = useState(null);

  async function resolve(confirmed) {
    setSaving(true);
    setError(null);
    try {
      const fields = confirmed
        ? { confidence: 1.0, roster_conflict: false }
        : {
          confidence: 1.0,
          roster_conflict: false,
          detail: `${item.detail ? `${item.detail} — ` : ""}User correction: ${text.trim()}`,
        };
      await api.correctEvent(jobId, item.idx, fields);
      onResolved();
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  }

  return (
    <div className="clarify-card">
      {item.referenceFrame
        ? <EventThumb jobId={jobId} framePath={item.referenceFrame} onEnlarge={setEnlargedSrc} />
        : <div className="event-thumb missing clarify-no-photo" title="No photo was captured for this moment">no photo</div>}
      <div className="clarify-body">
        <div className="clarify-question">
          What occurred here{typeof item.timestamp === "number" ? ` (${item.timestamp.toFixed(1)}s)` : ""}?
        </div>
        <div className="clarify-photo-note">
          AI's read: {item.detail || item.event.replace(/_/g, " ")}
        </div>
        {item.referenceFrameShowsSubject === false && (
          <div className="clarify-photo-note visibility-warning">
            The camera may not have clearly shown this moment - the read above may be a best guess.
          </div>
        )}
        {error && <div className="banner">{error}</div>}
        <div className="clarify-actions">
          <button type="button" className="clarify-yes" disabled={saving} onClick={() => resolve(true)}>
            ✓ That's right
          </button>
        </div>
        <div className="clarify-other-row">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Describe what actually happened"
          />
          <button type="button" disabled={saving || !text.trim()} onClick={() => resolve(false)}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      {enlargedSrc && <ImageLightbox src={enlargedSrc} onClose={() => setEnlargedSrc(null)} />}
    </div>
  );
}

/** The default view of an expanded match row: your team, the opponent's
 * team, a plain-English turn-by-turn recap, and the result - the "important
 * information" a player actually wants, per the redesign this replaces (the
 * old default was either a raw event-by-event stepper or a flat corrections
 * list, with no single place showing team/recap/result together at a
 * glance). Anything the system isn't confident about surfaces right here as
 * a targeted question with a photo - species identity (existing
 * ClarificationCard, reused via ClarificationQueue.jsx's named export),
 * "what occurred here" for non-identity low-confidence/roster-conflict
 * events (GenericOccurrenceCard), and "who won this match" when neither the
 * vision model nor the OCR tier ever resolved a winner (WinnerCard) - rather
 * than requiring a separate click into a raw table to find out something
 * needs a look. "Show every event instead" still reaches the exhaustive,
 * ungated MatchEvents.jsx view underneath for the rare low-level field that
 * needs hand-correcting outside these three question types. */
export default function MatchSummary({ jobId, events, matchNumber, onCorrected }) {
  const [showAll, setShowAll] = useState(false);

  const matchEvents = useMemo(
    () => (events || []).map((e, i) => ({ ...e, __idx: i })).filter((e) => e.match === matchNumber),
    [events, matchNumber],
  );
  const teamPreview = matchEvents.find((e) => e.event === "team_preview");
  const battleEnds = matchEvents.filter((e) => e.event === "battle_end");
  const winner = battleEnds.find((e) => e.winner === "player" || e.winner === "opponent")?.winner || "unknown";

  const frames = useMemo(() => buildBattleTimeline(events, matchNumber), [events, matchNumber]);
  const recapFrames = useMemo(() => frames.filter((f) => RECAP_EVENT_TYPES.has(f.event)), [frames]);

  // VGC Battle Intelligence Manual per-turn reports (added 2026-07-09) - GET
  // /jobs/{id}/strategic-analysis already existed (see backend/main.py) but
  // was never called from the frontend before this. Fetched once per job
  // (it covers every match in one call, same shape as api.report/api.record),
  // not re-fetched on matchNumber changes - matchStrategic below just picks
  // this match's own momentum_timeline back out of the full response.
  // Silently falls back to no per-turn intel (not an error banner) if the
  // fetch fails or the match has no field_state/turn data - the base recap
  // above already works fine without it, so this is a pure enhancement.
  const [strategicResults, setStrategicResults] = useState(null);
  useEffect(() => {
    let cancelled = false;
    api.strategicAnalysis(jobId)
      .then((results) => { if (!cancelled) setStrategicResults(results); })
      .catch(() => { if (!cancelled) setStrategicResults([]); });
    return () => { cancelled = true; };
  }, [jobId]);

  const turnReports = useMemo(() => {
    const byTurn = new Map();
    const matchResult = (strategicResults || []).find((r) => r.match === matchNumber);
    for (const entry of matchResult?.momentum_timeline || []) {
      byTurn.set(entry.turn, entry);
    }
    return byTurn;
  }, [strategicResults, matchNumber]);

  const identityGroups = useMemo(() => buildClarificationQueue(events, matchNumber), [events, matchNumber]);
  const winnerInfo = useMemo(() => buildWinnerClarification(events, matchNumber), [events, matchNumber]);
  const genericItems = useMemo(() => buildGenericClarifications(events, matchNumber), [events, matchNumber]);
  const totalQuestions = identityGroups.length + genericItems.length + (winnerInfo ? 1 : 0);

  if (showAll) {
    return (
      <div className="clarify-wrapper">
        <button type="button" className="link-button" onClick={() => setShowAll(false)}>
          ← Back to match summary
        </button>
        <MatchEvents jobId={jobId} events={events} matchNumber={matchNumber} onCorrected={onCorrected} />
      </div>
    );
  }

  const playerTeam = namesOf(teamPreview?.player_team);
  const opponentTeam = namesOf(teamPreview?.opponent_team);
  const playerBrought = namesOf(teamPreview?.player_brought);
  const opponentBrought = namesOf(teamPreview?.opponent_brought);

  const resultCls = winner === "player" ? "good" : winner === "opponent" ? "bad" : "warn";
  const resultText = winner === "player" ? "You won" : winner === "opponent" ? "You lost" : "Unknown - see below";

  return (
    <div className="match-summary">
      {totalQuestions > 0 && (
        <div className="note-banner warn">
          {totalQuestions} question{totalQuestions === 1 ? "" : "s"} need your input for this match - answer
          below to lock in an accurate record for training/skill analysis.
        </div>
      )}

      {winnerInfo && <WinnerCard jobId={jobId} winnerInfo={winnerInfo} onResolved={onCorrected} />}

      <div className="summary-teams">
        <div className="summary-team">
          <h4>Your team</h4>
          <div>{playerTeam.join(", ") || "—"}</div>
          <div className="muted">Brought: {playerBrought.join(", ") || "—"}</div>
        </div>
        <div className="summary-team">
          <h4>Opponent's team</h4>
          <div>{opponentTeam.join(", ") || "—"}</div>
          <div className="muted">Brought: {opponentBrought.join(", ") || "—"}</div>
        </div>
      </div>

      <div className={`summary-result ${resultCls}`}>Result: {resultText}</div>

      <h4 className="summary-heading">Turn-by-turn recap</h4>
      {recapFrames.length ? (
        <div className="summary-recap">
          {(() => {
            // One compact battle-intelligence line per turn (not per event) -
            // shown right before the FIRST recap frame that turn covers, so a
            // turn with several events (e.g. two moves + a faint) only gets
            // one report line, not one per event. See turnIntelTooltip's own
            // docstring for what's in the hover tooltip.
            let lastTurnShown = null;
            return recapFrames.map((f) => {
              const report = f.turn != null && f.turn !== lastTurnShown ? turnReports.get(f.turn) : null;
              if (f.turn != null) lastTurnShown = f.turn;
              return (
                <div key={f.idx}>
                  {report && (
                    <div className="recap-turn-intel" title={turnIntelTooltip(report)}>
                      Turn {f.turn}: <strong>{report.position_score.label}</strong> — {report.risk_management.guidance}
                    </div>
                  )}
                  <div className="recap-line">
                    {typeof f.timestamp === "number" && <span className="recap-time">{f.timestamp.toFixed(1)}s</span>}
                    <span>{f.caption}</span>
                  </div>
                </div>
              );
            });
          })()}
        </div>
      ) : (
        <div className="empty">No events recorded for this match.</div>
      )}

      {(identityGroups.length > 0 || genericItems.length > 0) && (
        <>
          <h4 className="summary-heading">Worth a quick confirm</h4>
          {identityGroups.map((g) => (
            <ClarificationCard
              key={g.key}
              jobId={jobId}
              group={g}
              frameContext={frameContextFor(frames, g)}
              onResolved={onCorrected}
            />
          ))}
          {genericItems.map((item) => (
            <GenericOccurrenceCard key={item.idx} jobId={jobId} item={item} onResolved={onCorrected} />
          ))}
        </>
      )}

      <button type="button" className="link-button" onClick={() => setShowAll(true)}>
        Show every event instead
      </button>
    </div>
  );
}
