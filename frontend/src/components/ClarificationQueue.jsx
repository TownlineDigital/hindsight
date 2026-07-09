import { useMemo, useState } from "react";
import { api } from "../api.js";
import { buildClarificationQueue, frameContextFor } from "../lib/clarifications.js";
import { buildBattleTimeline } from "../lib/battleTimeline.js";
import MatchEvents, { EventThumb, ImageLightbox } from "./MatchEvents.jsx";

/** One grouped question: "is this really <guess>?" with a big one-click
 * confirm (the common case - the AI is usually right, it's just flagging
 * its own uncertainty), a handful of alternate-candidate buttons, and an
 * "Other" free-text fallback for when none of the short list is correct.
 * Confirming applies the chosen species to every event in the group at
 * once (see lib/clarifications.js's grouping) via as many PATCH calls as
 * there are events - no new backend endpoint needed, since the existing
 * per-event correction endpoint already merges whatever fields it's given.
 *
 * `frameContext` ({ ownHp, ownStatus, others }, see lib/clarifications.js)
 * disambiguates a doubles photo showing 2 Pokemon per side - NOT by drawing
 * a circle on the image (deliberately not built; see frameContextFor's own
 * docstring for why a coordinate overlay would be unreliable here), but by
 * naming the HP percentage each active Pokemon should read at this turn -
 * every capture style observed so far prints that percentage right next to
 * each Pokemon's name on screen, so it's a number the user can actually
 * match against what's visibly there, not a guessed pixel position.
 *
 * `group.referenceFrameShowsSubject` (true/false/null - see
 * lib/clarifications.js) is a SEPARATE, honest cross-check: Pokemon
 * Champions' camera moves dynamically across the field, so the photo
 * attached to an event (picked by nearest timestamp alone) isn't guaranteed
 * to actually show the relevant side at all - see analyze_matches.py's
 * cross_check_reference_frame_visibility. When that check ran and came back
 * False, the HP%-matching note above is suppressed (there's nothing to
 * match against) in favor of a plain warning that the camera likely wasn't
 * on this Pokemon at that moment. null means the check simply didn't run
 * (--use-accuracy-addons wasn't enabled for this job, or this is the
 * team_preview/no-photo fallback) - treated the same as "unknown", never as
 * a stand-in for false. */
// Exported so MatchSummary.jsx can embed the exact same identity-question
// card inline in the new default match view, instead of duplicating this
// markup/resolve-logic a second time - see MatchSummary.jsx's own docstring
// for why the Matches tab moved to that as the default landing view.
export function ClarificationCard({ jobId, group, frameContext, onResolved }) {
  const [otherOpen, setOtherOpen] = useState(false);
  const [otherText, setOtherText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [enlargedSrc, setEnlargedSrc] = useState(null);

  const actorLabel = group.actor === "opponent" ? "Opponent's" : "Your";
  const altCandidates = group.candidates.filter((c) => c !== group.guessedSpecies);

  async function resolve(species) {
    const trimmed = String(species || "").trim();
    if (!trimmed) return;
    setSaving(true);
    setError(null);
    try {
      // confidence: 1.0 and roster_conflict: false are set alongside the
      // species fix so this group can't reappear in the queue next render
      // just because its stored confidence/flag never got refreshed -
      // lib/clarifications.js's needsClarification() checks exactly these
      // two fields (plus `corrected`, which the backend sets automatically).
      await Promise.all(
        group.eventIndices.map((idx) =>
          api.correctEvent(jobId, idx, { pokemon: trimmed, confidence: 1.0, roster_conflict: false }),
        ),
      );
      onResolved();
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  }

  return (
    <div className="clarify-card">
      {group.referenceFrame
        ? <EventThumb jobId={jobId} framePath={group.referenceFrame} onEnlarge={setEnlargedSrc} />
        : (
          <div className="event-thumb missing clarify-no-photo" title="No photo was captured for this Pokemon anywhere in this match">
            no photo
          </div>
        )}
      <div className="clarify-body">
        <div className="clarify-question">
          {actorLabel} Pokémon — currently read as <b>{group.guessedSpecies}</b>
          {group.count > 1 ? ` (${group.count} sightings)` : ""}. Is that right?
        </div>
        {group.isTeamPreviewFallback && (
          <div className="clarify-photo-note">
            No photo of this specific sighting was captured — showing the team preview screen instead, so you
            can at least check it against the roster.
          </div>
        )}
        {!group.referenceFrame && (
          <div className="clarify-photo-note">
            No photo at all was captured for this Pokémon in this match. Check the Battle Replay tab (it may
            still have a nearby frame) or answer from what you remember of the match — the buttons below still
            apply everywhere this guess showed up.
          </div>
        )}
        {group.referenceFrameShowsSubject === false && (
          <div className="clarify-photo-note visibility-warning">
            <b>{group.guessedSpecies}</b>'s name wasn't found readable anywhere in this photo — the camera may
            have been pointed elsewhere at this exact moment (Pokémon Champions' camera moves dynamically across
            the field, so a photo isn't guaranteed to show every Pokémon in play). Check the Battle Replay tab for
            a nearby frame that might show it, or answer from what you remember of the match.
          </div>
        )}
        {!!group.referenceFrame && !group.isTeamPreviewFallback && group.referenceFrameShowsSubject !== false
          && typeof frameContext.ownHp === "number" && (
          <div className="clarify-photo-note">
            At this moment, this Pokémon should read about <b>{Math.round(frameContext.ownHp)}% HP</b> on
            screen{frameContext.ownStatus ? <> and show <b>{frameContext.ownStatus}</b></> : ""} — match that
            number against what's printed in the photo.
            {frameContext.others.length > 0 && (
              <>
                {" "}The other Pokémon active alongside it was{" "}
                {frameContext.others.map((o, i) => (
                  <span key={o.species}>
                    {i > 0 ? " and " : ""}
                    <b>{o.species}</b>{typeof o.hp === "number" ? ` (~${Math.round(o.hp)}% HP)` : ""}
                  </span>
                ))}
                .
              </>
            )}
          </div>
        )}
        {error && <div className="banner">{error}</div>}
        <div className="clarify-actions">
          <button type="button" className="clarify-yes" disabled={saving} onClick={() => resolve(group.guessedSpecies)}>
            ✓ Yes, that's right
          </button>
          {altCandidates.map((c) => (
            <button type="button" key={c} className="clarify-alt" disabled={saving} onClick={() => resolve(c)}>
              {c}
            </button>
          ))}
          <button
            type="button"
            className="clarify-alt"
            disabled={saving}
            onClick={() => setOtherOpen((v) => !v)}
          >
            Other…
          </button>
        </div>
        {otherOpen && (
          <div className="clarify-other-row">
            <input
              value={otherText}
              onChange={(e) => setOtherText(e.target.value)}
              placeholder="Type the correct Pokémon"
            />
            <button type="button" disabled={saving || !otherText.trim()} onClick={() => resolve(otherText)}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        )}
      </div>
      {enlargedSrc && <ImageLightbox src={enlargedSrc} onClose={() => setEnlargedSrc(null)} />}
    </div>
  );
}

/** Default content of the Matches tab's "Corrections list" view - a short
 * list of grouped identity questions (usually zero to a handful) instead of
 * every single event needing a look, per lib/clarifications.js. A "Show
 * every event instead" link still reaches the exhaustive per-event
 * MatchEvents view underneath, for the rare case a low-level field (HP,
 * status, an item/ability call) needs hand-correcting rather than a
 * species guess. */
export default function ClarificationQueue({ jobId, events, matchNumber, onCorrected }) {
  const [showAll, setShowAll] = useState(false);
  const groups = useMemo(() => buildClarificationQueue(events, matchNumber), [events, matchNumber]);
  // Reuses BattleReplay.jsx's own turn-by-turn reconstruction purely to
  // answer "what HP% should this Pokemon (and anyone else active alongside
  // it) read at this exact photo" - see lib/clarifications.js's
  // frameContextFor() and referenceFrameEventIdx.
  const frames = useMemo(() => buildBattleTimeline(events, matchNumber), [events, matchNumber]);

  if (showAll) {
    return (
      <div className="clarify-wrapper">
        <button type="button" className="link-button" onClick={() => setShowAll(false)}>
          ← Back to clarifying questions
        </button>
        <MatchEvents jobId={jobId} events={events} matchNumber={matchNumber} onCorrected={onCorrected} />
      </div>
    );
  }

  return (
    <div className="clarify-wrapper">
      {groups.length ? (
        <>
          <div className="note-banner">
            {groups.length} identity read{groups.length === 1 ? "" : "s"} worth a quick confirm for this match —
            answering one applies it to every sighting of that Pokémon at once.
          </div>
          {groups.map((g) => (
            <ClarificationCard
              key={g.key}
              jobId={jobId}
              group={g}
              frameContext={frameContextFor(frames, g)}
              onResolved={onCorrected}
            />
          ))}
        </>
      ) : (
        <div className="empty">Nothing to confirm — every Pokémon read for this match was confident.</div>
      )}
      <button type="button" className="link-button" onClick={() => setShowAll(true)}>
        Show every event instead
      </button>
    </div>
  );
}
