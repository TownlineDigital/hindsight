// Tests for clarifications.js's buildClarificationQueue() - the grouping
// logic that collapses repeated low-confidence identity reads into a small
// number of clarification questions (see ClarificationQueue.jsx for the UI).
//
// Uses Node's built-in test runner (node:test) + node:assert/strict - same
// zero-dependency convention as battleTimeline.test.mjs.
//
// Run (from frontend/):  node --test src/lib/clarifications.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildClarificationQueue, frameContextFor, buildWinnerClarification, buildGenericClarifications,
} from "./clarifications.js";
import { buildBattleTimeline } from "./battleTimeline.js";

function teamPreview(overrides = {}) {
  return {
    event: "team_preview", match: 1, actor: "both", timestamp: 0,
    player_brought: "Rotom, Incineroar, Urshifu, Amoonguss",
    opponent_brought: "Rillaboom, Whimsicott, Farigiraf, Indeedee",
    ...overrides,
  };
}

test("repeated low-confidence sightings of the same guessed species collapse into one group", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.6, timestamp: 5, reference_frame: "match_1/f5.jpg" },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 6 },
    { event: "pokemon_fainted", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.7, timestamp: 20 },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].guessedSpecies, "Rillaboom");
  assert.equal(groups[0].actor, "opponent");
  assert.equal(groups[0].count, 3);
  assert.deepEqual(groups[0].eventIndices, [1, 2, 3]);
});

test("confident (>= threshold) events are excluded entirely - the common case yields zero questions", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "player", pokemon: "Rotom", confidence: 1.0, timestamp: 5 },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.95, timestamp: 6 },
  ];
  assert.deepEqual(buildClarificationQueue(events, 1), []);
});

test("a roster_conflict event is included even at high confidence", () => {
  const events = [
    teamPreview(),
    {
      event: "move_used", match: 1, actor: "opponent", pokemon: "Charizard", confidence: 0.95,
      roster_conflict: true, roster_conflict_species: ["Staraptor"], timestamp: 5, reference_frame: "match_1/f5.jpg",
    },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].guessedSpecies, "Charizard");
});

test("an already-corrected event is never asked about again, even if still low-confidence", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, corrected: true, timestamp: 5 },
  ];
  assert.deepEqual(buildClarificationQueue(events, 1), []);
});

test("team_preview itself never becomes a clarification question", () => {
  const events = [teamPreview({ confidence: 0.5 })];
  assert.deepEqual(buildClarificationQueue(events, 1), []);
});

test("different guessed species, or different sides, produce separate groups", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 5, reference_frame: "match_1/a.jpg" },
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 6, reference_frame: "match_1/b.jpg" },
    { event: "move_used", match: 1, actor: "player", pokemon: "Rotom", confidence: 0.5, timestamp: 7, reference_frame: "match_1/c.jpg" },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups.length, 3);
});

test("candidates are ordered: current guess first, then flagged roster-conflict alternatives, then the rest of that side's brought roster, de-duplicated", () => {
  const events = [
    teamPreview(),
    {
      event: "move_used", match: 1, actor: "opponent", pokemon: "Charizard", confidence: 0.5,
      roster_conflict: true, roster_conflict_species: ["Rillaboom"], timestamp: 5, reference_frame: "match_1/f5.jpg",
    },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.deepEqual(groups[0].candidates, ["Charizard", "Rillaboom", "Whimsicott", "Farigiraf", "Indeedee"]);
});

test("events from a different match number are ignored", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 2, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 5 },
  ];
  assert.deepEqual(buildClarificationQueue(events, 1), []);
});

test("minConfidence reflects the lowest confidence seen across the group's events", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.8, timestamp: 5, reference_frame: "match_1/f5.jpg" },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.4, timestamp: 6 },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].minConfidence, 0.4);
});

test("a group picks up the first available reference_frame among its events", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 5 },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 6, reference_frame: "match_1/f2.jpg" },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].referenceFrame, "match_1/f2.jpg");
  // Index 2 - the hp_change event above, at position 2 in the raw events array
  // (0: team_preview, 1: move_used, 2: hp_change) - is the one that actually
  // carried the photo, so the UI can look up "what else was on the field" at
  // that exact moment (see ClarificationQueue.jsx's doubles disambiguation).
  assert.equal(groups[0].referenceFrameEventIdx, 2);
});

test("player-side groups sort before opponent-side groups", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 5, reference_frame: "match_1/a.jpg" },
    { event: "move_used", match: 1, actor: "player", pokemon: "Rotom", confidence: 0.5, timestamp: 6, reference_frame: "match_1/b.jpg" },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].actor, "player");
  assert.equal(groups[1].actor, "opponent");
});

test("no team_preview in the match still works, falling back to just the guess + roster-conflict candidates", () => {
  const events = [
    {
      event: "move_used", match: 1, actor: "opponent", pokemon: "Charizard", confidence: 0.5,
      roster_conflict: true, roster_conflict_species: ["Staraptor"], timestamp: 5, reference_frame: "match_1/f5.jpg",
    },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.deepEqual(groups[0].candidates, ["Charizard", "Staraptor"]);
});

test("when none of a group's OWN flagged events have a photo, it borrows one from a different (confident) sighting of the same Pokemon", () => {
  const events = [
    teamPreview(),
    // The flagged event itself has no reference_frame...
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5 },
    // ...but a separate, fully confident sighting of the same Pokemon does.
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 1.0, timestamp: 8, reference_frame: "match_1/f9.jpg" },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].referenceFrame, "match_1/f9.jpg");
  assert.equal(groups[0].isTeamPreviewFallback, false);
});

test("borrowing a photo from another sighting never crosses sides or species - with nothing valid to borrow, the group is dropped entirely (no photo to show)", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5 },
    // Same species name but the PLAYER's side - must not be borrowed for the opponent's group.
    { event: "hp_change", match: 1, actor: "player", pokemon: "Whimsicott", confidence: 1.0, timestamp: 6, reference_frame: "match_1/wrong-side.jpg" },
    // A different species entirely - must not be borrowed either.
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Farigiraf", confidence: 1.0, timestamp: 7, reference_frame: "match_1/wrong-species.jpg" },
  ];
  assert.deepEqual(buildClarificationQueue(events, 1), []);
});

test("as a last resort, falls back to team_preview's own reference frame and flags it as such", () => {
  const events = [
    teamPreview({ reference_frame: "match_1/preview.jpg" }),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5 },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].referenceFrame, "match_1/preview.jpg");
  assert.equal(groups[0].isTeamPreviewFallback, true);
});

test("with no photo anywhere - not even team_preview's - the group is dropped entirely rather than shown with a 'no photo' placeholder", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5 },
  ];
  assert.deepEqual(buildClarificationQueue(events, 1), []);
});

test("frameContextFor reports the guessed Pokemon's own HP% and the OTHER Pokemon active alongside it, with its HP% too", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 1, timestamp: 4, player_active: "Rotom, Incineroar", opponent_active: "Rillaboom, Whimsicott" },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Rillaboom", hp_percent: 68, timestamp: 4.5 },
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5, reference_frame: "match_1/f5.jpg" },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Whimsicott", hp_percent: 20, timestamp: 5, reference_frame: "match_1/f5.jpg" },
  ];
  const groups = buildClarificationQueue(events, 1);
  const frames = buildBattleTimeline(events, 1);
  const ctx = frameContextFor(frames, groups[0]);
  assert.equal(ctx.ownHp, 20);
  assert.deepEqual(ctx.others, [{ species: "Rillaboom", hp: 68, status: null }]);
});

test("frameContextFor's others is empty in singles - or whenever nothing else is active alongside the guess", () => {
  const events = [
    { event: "team_preview", match: 1, timestamp: 0, player_brought: "Rotom", opponent_brought: "Rillaboom" },
    { event: "field_state", match: 1, timestamp: 4, player_active: "Rotom", opponent_active: "Rillaboom" },
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 5, reference_frame: "match_1/f5.jpg" },
  ];
  const groups = buildClarificationQueue(events, 1);
  const frames = buildBattleTimeline(events, 1);
  assert.deepEqual(frameContextFor(frames, groups[0]).others, []);
});

test("referenceFrameShowsSubject is carried through from the source event's reference_frame_shows_subject field", () => {
  const events = [
    teamPreview(),
    {
      event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5,
      reference_frame: "match_1/f5.jpg", reference_frame_shows_subject: false,
    },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].referenceFrameShowsSubject, false);
});

test("referenceFrameShowsSubject is null (not undefined) when the visibility addon never ran on the source event", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5,
      reference_frame: "match_1/f5.jpg" },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].referenceFrameShowsSubject, null);
});

test("referenceFrameShowsSubject is carried through when the photo is BORROWED from a different confident sighting", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5 },
    {
      event: "hp_change", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 1.0, timestamp: 8,
      reference_frame: "match_1/f9.jpg", reference_frame_shows_subject: false,
    },
  ];
  const groups = buildClarificationQueue(events, 1);
  assert.equal(groups[0].referenceFrame, "match_1/f9.jpg");
  assert.equal(groups[0].referenceFrameShowsSubject, false);
});

test("referenceFrameShowsSubject is null for the team_preview-fallback case (the true-no-photo case no longer produces a group at all - see the dedicated 'dropped entirely' test above)", () => {
  const withFallback = buildClarificationQueue([
    teamPreview({ reference_frame: "match_1/preview.jpg" }),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5 },
  ], 1);
  assert.equal(withFallback[0].referenceFrameShowsSubject, null);
});

test("frameContextFor itself still safely returns all-null/empty when handed a group with no photo (defensive - buildClarificationQueue itself never produces such a group anymore, but frameContextFor is a separately-usable utility)", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Whimsicott", confidence: 0.5, timestamp: 5 },
  ];
  const frames = buildBattleTimeline(events, 1);
  const noPhotoGroup = {
    key: "opponent::Whimsicott", actor: "opponent", guessedSpecies: "Whimsicott",
    referenceFrame: null, referenceFrameEventIdx: null, isTeamPreviewFallback: false,
  };
  assert.deepEqual(frameContextFor(frames, noPhotoGroup), { ownHp: null, ownStatus: null, others: [] });
});

// --- buildWinnerClarification -------------------------------------------
// The real, found gap this fixes: matches 4/5 of a real 10-match production
// run both came back winner="unknown" because a stream disconnect covered
// the actual result screen in every frame either the vision model or the
// OCR tier searched - no amount of AI retrying could have found one. This
// surfaces "who won?" as its own answerable question instead of a dead-end
// ⚠ badge with no path to fix it.

function battleEnd(overrides = {}) {
  return { event: "battle_end", match: 1, timestamp: 100, winner: "unknown", ...overrides };
}

test("no battle_end event in the match at all -> null (nothing to ask)", () => {
  const events = [teamPreview()];
  assert.equal(buildWinnerClarification(events, 1), null);
});

test("winner already resolved -> null, even with other unresolved fields elsewhere", () => {
  const events = [teamPreview(), battleEnd({ winner: "player" })];
  assert.equal(buildWinnerClarification(events, 1), null);
});

test("winner unknown -> returns eventIndices covering every battle_end for this match", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 1.0, timestamp: 90, reference_frame: "match_1/late.jpg" },
    battleEnd({ timestamp: 95 }),
    battleEnd({ timestamp: 100 }),
  ];
  const info = buildWinnerClarification(events, 1);
  assert.deepEqual(info.eventIndices, [2, 3]);
});

test("if ANY battle_end for this match already resolved, treated as resolved (no question) even if a duplicate still says unknown", () => {
  // Mirrors the real shape: an OCR-derived battle_end and the main
  // pipeline's own read_winner() result can disagree in raw storage order,
  // but a real resolved winner anywhere means this isn't actually unknown.
  const events = [teamPreview(), battleEnd({ timestamp: 95 }), battleEnd({ timestamp: 100, winner: "opponent" })];
  assert.equal(buildWinnerClarification(events, 1), null);
});

test("borrows the LATEST (by timestamp) non-team_preview reference_frame in the match as a fallback photo", () => {
  const events = [
    teamPreview({ reference_frame: "match_1/preview.jpg" }),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 1.0, timestamp: 50, reference_frame: "match_1/early.jpg" },
    { event: "hp_change", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 1.0, timestamp: 90, reference_frame: "match_1/late.jpg" },
    battleEnd(),
  ];
  const info = buildWinnerClarification(events, 1);
  assert.equal(info.referenceFrame, "match_1/late.jpg");
  assert.equal(info.referenceFrameTimestamp, 90);
  assert.equal(info.isNearestFallback, true);
});

test("team_preview's own reference_frame is never borrowed as the winner fallback photo - with nothing else to borrow, returns null rather than a card with no photo", () => {
  const events = [
    teamPreview({ reference_frame: "match_1/preview.jpg" }),
    battleEnd(),
  ];
  assert.equal(buildWinnerClarification(events, 1), null);
});

test("no photo anywhere in the match -> null (a 'who won?' card with a 'no photo' placeholder instead of the result screen would read as broken)", () => {
  const events = [teamPreview(), battleEnd()];
  assert.equal(buildWinnerClarification(events, 1), null);
});

test("events from a different match number are ignored by buildWinnerClarification", () => {
  const events = [teamPreview(), { ...battleEnd(), match: 2 }];
  assert.equal(buildWinnerClarification(events, 1), null);
});

// --- buildGenericClarifications ------------------------------------------
// The "what occurred here?" counterpart to species-identity questions - for
// flagged events that AREN'T shaped like a single-Pokemon guess (no
// singular `pokemon` field, or no `actor`), so they'd otherwise be invisible
// outside the raw "Show every event" table.

test("a low-confidence field_state event (no singular pokemon field) surfaces as a generic item", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 1, timestamp: 10, confidence: 0.6, detail: "Trick Room active", reference_frame: "match_1/f.jpg" },
  ];
  const items = buildGenericClarifications(events, 1);
  assert.equal(items.length, 1);
  assert.equal(items[0].event, "field_state");
  assert.equal(items[0].idx, 1);
});

test("a flagged event with no reference_frame at all is not surfaced - a 'what occurred here?' card with a 'no photo' placeholder instead of an actual photo would read as broken", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 1, timestamp: 10, confidence: 0.6, detail: "Trick Room active" },
  ];
  assert.deepEqual(buildGenericClarifications(events, 1), []);
});

test("a confident field_state event is not surfaced", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 1, timestamp: 10, confidence: 1.0 },
  ];
  assert.deepEqual(buildGenericClarifications(events, 1), []);
});

test("an identity-shaped event (has pokemon + actor) is NEVER double-counted as generic, even at low confidence", () => {
  const events = [
    teamPreview(),
    { event: "move_used", match: 1, actor: "opponent", pokemon: "Rillaboom", confidence: 0.5, timestamp: 5, reference_frame: "match_1/f5.jpg" },
  ];
  assert.deepEqual(buildGenericClarifications(events, 1), []);
  // ...but IS picked up by the identity queue instead:
  assert.equal(buildClarificationQueue(events, 1).length, 1);
});

test("team_preview itself is never surfaced as a generic question, even at low confidence", () => {
  const events = [teamPreview({ confidence: 0.5 })];
  assert.deepEqual(buildGenericClarifications(events, 1), []);
});

test("battle_end is never surfaced as a generic question - buildWinnerClarification owns that instead", () => {
  const events = [teamPreview(), battleEnd({ confidence: 0.5 })];
  assert.deepEqual(buildGenericClarifications(events, 1), []);
});

test("a roster_conflict event with no singular pokemon field still surfaces generically", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 1, timestamp: 10, confidence: 1.0, roster_conflict: true, reference_frame: "match_1/f.jpg" },
  ];
  const items = buildGenericClarifications(events, 1);
  assert.equal(items.length, 1);
});

test("an already-corrected generic event is not surfaced again", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 1, timestamp: 10, confidence: 0.5, corrected: true },
  ];
  assert.deepEqual(buildGenericClarifications(events, 1), []);
});

test("generic items are sorted by timestamp and carry the source event's detail/confidence/photo fields", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 1, timestamp: 20, confidence: 0.6, detail: "second", reference_frame: "match_1/g.jpg" },
    {
      event: "field_state", match: 1, timestamp: 10, confidence: 0.4, detail: "first",
      reference_frame: "match_1/f.jpg", reference_frame_shows_subject: false,
    },
  ];
  const items = buildGenericClarifications(events, 1);
  assert.deepEqual(items.map((i) => i.detail), ["first", "second"]);
  assert.equal(items[0].confidence, 0.4);
  assert.equal(items[0].referenceFrame, "match_1/f.jpg");
  assert.equal(items[0].referenceFrameShowsSubject, false);
});

test("events from a different match number are ignored by buildGenericClarifications", () => {
  const events = [
    teamPreview(),
    { event: "field_state", match: 2, timestamp: 10, confidence: 0.5 },
  ];
  assert.deepEqual(buildGenericClarifications(events, 1), []);
});
