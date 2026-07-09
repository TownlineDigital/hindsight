// Groups repeated low-confidence/roster-conflict IDENTITY reads within one
// match into a small number of clarification QUESTIONS, instead of leaving
// every flagged event as its own separate review item - e.g. five different
// "worth checking" events that are all actually the same uncertain Charizard
// sighting collapse into one "which Pokemon is this?" question, answered
// once and applied everywhere that same guess showed up. This is what makes
// the Matches tab's Corrections list ask "the smallest amount of questions"
// rather than requiring every single event to be individually reviewed.
//
// See ClarificationQueue.jsx for the UI this drives, and lib/confidence.js
// for the shared confidence bar (pulled into its own plain-.js module so
// this file - and its node:test suite - never has to import a .jsx file).
//
// Deliberately scoped to events that carry a single `pokemon` field
// (move_used, hp_change, pokemon_fainted, status_inflicted, terastallized,
// item_or_ability_activated, pokemon_sent_out) - team_preview's own
// roster/lead read is a different shape (several species named in one
// event) and keeps its existing dedicated section/correction form in
// MatchEvents.jsx completely unchanged; field_state events don't carry a
// singular `pokemon` field either and are excluded the same way.

import { namesOf } from "./battleTimeline.js";
import { LOW_CONFIDENCE_THRESHOLD } from "./confidence.js";

/** True when this event's own identity read is uncertain enough to be
 * worth asking about - either a confidence below the shared threshold, or
 * the AI's own roster-conflict flag (a real, legal species that just wasn't
 * in this match's identified roster - see analyze_matches.flag_roster_conflicts).
 * Already-corrected events are excluded outright: a human already resolved
 * this one, so it shouldn't come back as a question again even if its
 * stored confidence/roster_conflict fields are stale (ClarificationQueue's
 * own resolve() also refreshes both fields on save, as a second guard
 * against exactly this). */
function needsClarification(e) {
  if (e.corrected === true) return false;
  const lowConfidence = typeof e.confidence === "number" && e.confidence < LOW_CONFIDENCE_THRESHOLD;
  return lowConfidence || e.roster_conflict === true;
}

/** Builds the reduced clarification queue for one match: one entry per
 * distinct (side, guessed species) pair among that match's uncertain
 * events, each carrying every event index a correction should apply to
 * once answered, a representative reference frame, and a short candidate
 * answer list - that side's confirmed team-preview "brought" roster, plus
 * any legal-but-out-of-roster species the AI itself flagged as a possible
 * alternative, plus the current guess itself. Deliberately NOT an
 * exhaustive dex list - the whole point is fewer choices, not more; an
 * "Other" free-text fallback (built into ClarificationQueue.jsx, not this
 * module) still covers the rare case where none of these are right.
 *
 * Returns [] when every identity read in the match was confident - the
 * common case, and the whole reason this exists instead of always showing
 * every event. Also drops any group that, after checking its own events, any
 * borrowed sighting of the same (side, species), and team_preview's own
 * roster screen, still has no photo at all: presenting a "no photo"
 * placeholder next to "is this really X?" reads as a broken UI rather than a
 * deliberate one, so these rare cases are left to the raw "Show every event"
 * table instead of a review card with nothing to actually look at. */
export function buildClarificationQueue(events, matchNumber) {
  const matchEvents = (events || [])
    .map((e, i) => ({ ...e, __idx: i }))
    .filter((e) => e.match === matchNumber);

  const teamPreview = matchEvents.find((e) => e.event === "team_preview");
  const broughtBySide = {
    player: teamPreview ? namesOf(teamPreview.player_brought) : [],
    opponent: teamPreview ? namesOf(teamPreview.opponent_brought) : [],
  };

  // A card asking "is this really X?" is useless without something to look
  // at. The flagged events themselves might not carry a reference_frame
  // (attach_reference_frames only tags an event when a sampled video frame
  // landed close enough to its timestamp - see analyze_matches.py), but a
  // DIFFERENT sighting of that exact same (side, species) elsewhere in the
  // match - even a fully confident one - very likely does, and is just as
  // valid a photo to judge the identity against. Scanned once, over every
  // non-team_preview event regardless of confidence, so a group can borrow
  // one even when none of its own flagged events have a photo.
  const anyReferenceFrameBySpecies = new Map();
  for (const e of matchEvents) {
    if (e.event === "team_preview" || !e.pokemon || !e.actor || !e.reference_frame) continue;
    const side = e.actor === "opponent" ? "opponent" : "player";
    const key = `${side}::${e.pokemon}`;
    if (!anyReferenceFrameBySpecies.has(key)) {
      anyReferenceFrameBySpecies.set(key, {
        frame: e.reference_frame, idx: e.__idx, showsSubject: e.reference_frame_shows_subject,
      });
    }
  }

  const groups = new Map();
  const order = [];

  for (const e of matchEvents) {
    if (e.event === "team_preview") continue;
    if (!e.pokemon || !e.actor) continue;
    if (!needsClarification(e)) continue;

    const side = e.actor === "opponent" ? "opponent" : "player";
    const key = `${side}::${e.pokemon}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        actor: side,
        guessedSpecies: e.pokemon,
        eventIndices: [],
        confidences: [],
        rosterConflictSpecies: new Set(),
        referenceFrame: null,
        referenceFrameEventIdx: null,
        referenceFrameShowsSubject: undefined,
      });
      order.push(key);
    }
    const g = groups.get(key);
    g.eventIndices.push(e.__idx);
    if (typeof e.confidence === "number") g.confidences.push(e.confidence);
    (e.roster_conflict_species || []).forEach((s) => g.rosterConflictSpecies.add(s));
    if (!g.referenceFrame && e.reference_frame) {
      g.referenceFrame = e.reference_frame;
      g.referenceFrameEventIdx = e.__idx;
      g.referenceFrameShowsSubject = e.reference_frame_shows_subject;
    }
  }

  return order
    .map((key) => {
      const g = groups.get(key);
      // Order matters here: the current guess first (so it renders as the
      // prominent "yes, that's right" option), then the AI's own flagged
      // alternatives, then the rest of that side's confirmed roster -
      // de-duplicated without disturbing that priority order.
      const seen = new Set();
      const candidates = [];
      [g.guessedSpecies, ...g.rosterConflictSpecies, ...broughtBySide[g.actor]].forEach((sp) => {
        if (sp && !seen.has(sp)) {
          seen.add(sp);
          candidates.push(sp);
        }
      });
      // Falls back to team_preview's own photo (the roster screen, showing
      // every icon at once) only as a last resort when NO sighting of this
      // Pokemon anywhere in the match has its own reference_frame -
      // genuinely rare, but still better than nothing to compare against.
      // ClarificationQueue.jsx labels this case differently (it's a roster
      // screen, not a photo of this specific sighting), via
      // isTeamPreviewFallback below.
      const ownFrame = g.referenceFrame
        ? { frame: g.referenceFrame, idx: g.referenceFrameEventIdx, showsSubject: g.referenceFrameShowsSubject }
        : null;
      const ownOrBorrowedFrame = ownFrame || anyReferenceFrameBySpecies.get(key) || null;
      const referenceFrame = (ownOrBorrowedFrame && ownOrBorrowedFrame.frame)
        || (teamPreview ? teamPreview.reference_frame : null) || null;
      return {
        key: g.key,
        actor: g.actor,
        guessedSpecies: g.guessedSpecies,
        count: g.eventIndices.length,
        eventIndices: g.eventIndices,
        minConfidence: g.confidences.length ? Math.min(...g.confidences) : null,
        referenceFrame,
        // The event index the photo actually came from, so the UI can look
        // up "who else was on the field in that exact photo" (see
        // ClarificationQueue.jsx) to help tell apart two Pokemon in a
        // doubles shot. Null for the team_preview fallback (that's the
        // roster screen, not a specific turn) and for the true no-photo case.
        referenceFrameEventIdx: ownOrBorrowedFrame ? ownOrBorrowedFrame.idx : null,
        isTeamPreviewFallback: !ownOrBorrowedFrame && !!referenceFrame,
        // true/false only when analyze_matches.py's --use-accuracy-addons
        // cross_check_reference_frame_visibility actually ran on the source
        // event (Pokemon Champions' camera moves dynamically, so a photo
        // picked by nearest-timestamp alone isn't guaranteed to show the
        // relevant side - see that function's docstring); null/undefined
        // means "not checked" (addon disabled, or this is the team_preview/
        // true-no-photo fallback, neither of which has a specific sighting
        // to check) - ClarificationQueue.jsx must treat that as "unknown",
        // never as a stand-in for false.
        referenceFrameShowsSubject: ownOrBorrowedFrame ? (ownOrBorrowedFrame.showsSubject ?? null) : null,
        candidates,
      };
    })
    .filter((g) => !!g.referenceFrame)
    .sort((a, b) => {
      if (a.actor !== b.actor) return a.actor === "player" ? -1 : 1;
      return a.guessedSpecies.localeCompare(b.guessedSpecies);
    });
}

/** True for an event that's a candidate for the per-species IDENTITY
 * question above - the same shape buildClarificationQueue itself requires
 * (a singular `pokemon` field plus a known `actor`, and not team_preview).
 * Exported so buildGenericClarifications below can skip exactly these -
 * anything low-confidence that ISN'T identity-shaped falls to the generic
 * "what occurred here" bucket instead of being silently dropped. */
function isIdentityCandidate(e) {
  return e.event !== "team_preview" && !!e.pokemon && !!e.actor;
}

/** Surfaces "who won this match?" as its own clarification when NEITHER
 * battle_end event for this match (there can be two - see analyze_matches.py:
 * an OCR-text-derived one with its own reference_frame, and the main
 * pipeline's own read_winner() result with none) ever resolved to "player"
 * or "opponent". This used to be silently left as a ⚠ badge on the match row
 * with no path to actually fix it - a real, found gap (see the winner-
 * detection investigation into matches 4/5 of a real 10-match run: BOTH
 * Gemini's vision read_winner AND the OCR tier came back empty because the
 * stream itself cut to a "be right back"/connection-drop screen right at the
 * marked match boundary - there was no result screen in ANY frame either one
 * searched, so no amount of retrying the AI would have found one. A human
 * who was actually watching, or who can scrub the source VOD, is the only
 * way this ever gets resolved).
 *
 * Returns null when there's nothing to ask (no battle_end event in this
 * match at all, or the winner is already known) - the common case - AND when
 * the winner genuinely is unknown but no photo could be found anywhere in
 * the match to show alongside the question either: a "who won?" card with a
 * "no photo" placeholder instead of the result screen it's implicitly
 * promising reads as broken, so that rare case is left to the raw "Show
 * every event" table (or the Battle Replay tab) instead of a review card
 * with nothing to actually look at.
 *
 * No reference_frame lives on a battle_end event itself (see
 * analyze_matches.py: attach_reference_frames only tags match_events sampled
 * inside the battle-event pipeline, never the team_preview/battle_end
 * synthetic events built afterward in the main loop) - the closest
 * borrowable photo is whichever event LATEST in the match (by timestamp,
 * excluding team_preview) happens to carry one, on the theory that the
 * actual end-of-match moment is closest to it chronologically. Flagged via
 * `isNearestFallback` (always true whenever this returns non-null, since
 * battle_end never has a photo of its own to prefer instead) so the UI can
 * be honest that this is an approximation, not literally a photo of the
 * result screen. */
export function buildWinnerClarification(events, matchNumber) {
  const matchEvents = (events || [])
    .map((e, i) => ({ ...e, __idx: i }))
    .filter((e) => e.match === matchNumber);

  const battleEnds = matchEvents.filter((e) => e.event === "battle_end");
  if (!battleEnds.length) return null;
  const resolved = battleEnds.some((e) => e.winner === "player" || e.winner === "opponent");
  if (resolved) return null;

  const withPhoto = matchEvents
    .filter((e) => e.event !== "team_preview" && e.reference_frame)
    .sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));
  const nearest = withPhoto.length ? withPhoto[withPhoto.length - 1] : null;
  if (!nearest) return null;

  return {
    eventIndices: battleEnds.map((e) => e.__idx),
    referenceFrame: nearest.reference_frame,
    referenceFrameTimestamp: nearest.timestamp,
    referenceFrameShowsSubject: nearest.reference_frame_shows_subject ?? null,
    isNearestFallback: true,
  };
}

/** The second half of "ask about anything the system isn't sure of": events
 * that are flagged the same way the identity questions are (low confidence
 * or a roster_conflict - see needsClarification above) but AREN'T shaped
 * like a single-Pokemon identity guess - a field_state read the accuracy
 * cross-checks disagreed with, an item/ability call, a weather/status read,
 * or any other event type this project adds later. These were previously
 * only visible by clicking through to the raw "Show every event" table one
 * row at a time; this surfaces them as their own "what occurred here?"
 * question, photo included, right alongside the identity questions.
 *
 * Deliberately NOT grouped the way identity sightings are - a repeated
 * identity guess is very likely the SAME underlying Pokemon seen several
 * times, but two flagged field_state/item events are each their own distinct
 * moment on the board, so collapsing them would risk hiding a real, separate
 * uncertain moment. One card per flagged event instead.
 *
 * team_preview is excluded (it has its own dedicated correction form
 * already, see MatchEvents.jsx's team-preview-section) and battle_end is
 * excluded (handled by buildWinnerClarification above, which asks the
 * more specific "who won?" question rather than a generic one). Also
 * excludes anything with no reference_frame at all - a "what occurred
 * here?" card with a "no photo" placeholder instead of an actual photo reads
 * as broken, so these fall to the raw "Show every event" table instead. */
export function buildGenericClarifications(events, matchNumber) {
  const matchEvents = (events || [])
    .map((e, i) => ({ ...e, __idx: i }))
    .filter((e) => e.match === matchNumber);

  return matchEvents
    .filter((e) => e.event !== "team_preview" && e.event !== "battle_end")
    .filter((e) => needsClarification(e))
    .filter((e) => !isIdentityCandidate(e))
    .filter((e) => !!e.reference_frame)
    .map((e) => ({
      idx: e.__idx,
      event: e.event,
      actor: e.actor || null,
      timestamp: e.timestamp,
      detail: e.detail || "",
      confidence: typeof e.confidence === "number" ? e.confidence : null,
      referenceFrame: e.reference_frame || null,
      referenceFrameShowsSubject: e.reference_frame_shows_subject ?? null,
    }))
    .sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));
}

/** In doubles, the reference photo a clarification card shows can have TWO
 * Pokemon active on the same side at once - but the question only names
 * one of them (the guessed species). A drawn circle/box pointing at the
 * right sprite was considered and deliberately NOT built: this project's
 * own accuracy_addons/hp_bar_reader.py already tried pinning fixed pixel
 * regions to HP-bar plates and documents, from real measurement, that the
 * broadcast overlay's plates are NOT pinned to a fixed position across
 * frames (its own docstring: a region that read correctly on one frame
 * missed by ~8px on another) - and that was for ONE streamer's fixed
 * overlay layout; a different video's layout (different webcam placement,
 * different HP-bar style) would be measured from nothing at all. Drawing a
 * circle from coordinates this shaky would risk confidently pointing at the
 * WRONG Pokemon, which is worse than not pointing at all.
 *
 * What's reliable instead: the exact HP PERCENTAGE each active Pokemon
 * should read at this turn, from this project's own event data - and every
 * capture style observed so far prints that percentage directly next to
 * each Pokemon's name on screen. Telling the user "this one should read
 * about 68% HP" lets them match a number that's already visibly printed in
 * the photo, rather than trusting a guessed pixel position. Uses
 * battleTimeline.js's own turn-by-turn reconstruction (`frames`, from
 * buildBattleTimeline(events, matchNumber) - same events/matchNumber the
 * group came from), keyed by the specific event index the group's photo
 * came from (`group.referenceFrameEventIdx` - null for the team_preview-
 * roster-screen fallback and the true no-photo case, where there's no
 * single turn's board state to look up).
 *
 * Returns { ownHp, ownStatus, others } - `ownHp`/`ownStatus` describe the
 * guessed species itself (null if that frame has no reading for it yet);
 * `others` is every OTHER Pokemon active on the same side at that same
 * moment ({ species, hp, status }), empty in singles or whenever nothing
 * else was active alongside the guess. */
export function frameContextFor(frames, group) {
  const empty = { ownHp: null, ownStatus: null, others: [] };
  if (!group || group.referenceFrameEventIdx == null || !group.referenceFrame) return empty;
  // A single captured photo is frequently attached to more than one event at
  // the same moment (e.g. a move_used AND the hp_change it caused both get
  // tagged with the same nearby video frame by attach_reference_frames.py).
  // referenceFrameEventIdx only records WHICH event happened to be the first
  // one carrying that photo - matching on that exact index alone would miss
  // a sibling event's HP update that landed a beat later in the event stream
  // but describes the exact same on-screen moment. Matching on the photo
  // PATH instead, and taking the last (most-up-to-date) frame among every
  // event that shares it, gives the fullest, most accurate state for what's
  // actually pictured. Falls back to the index match only if, for some
  // reason, no frame carries that path at all.
  const sharingPhoto = (frames || []).filter((f) => f.referenceFrame === group.referenceFrame);
  const frame = sharingPhoto.length
    ? sharingPhoto[sharingPhoto.length - 1]
    : (frames || []).find((f) => f.idx === group.referenceFrameEventIdx);
  if (!frame) return empty;
  const side = (group.actor === "opponent" ? frame.opponent : frame.player) || [];
  const own = side.find((m) => m.species === group.guessedSpecies) || null;
  const others = side
    .filter((m) => m.species && m.species !== group.guessedSpecies)
    .map((m) => ({ species: m.species, hp: m.hp, status: m.status }));
  return { ownHp: own ? own.hp : null, ownStatus: own ? own.status : null, others };
}
